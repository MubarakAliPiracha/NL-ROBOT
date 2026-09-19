"""HTTP/WebSocket bridge between the web UI and the PyBullet + Ollama PoC.

Runs PyBullet headless (DIRECT), reuses the planner/executor from
poc_ollama_pybullet.py, and streams robot state to the browser so the
three.js viewport can mirror the simulation.

Run from the repo root:
    py -3.13 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
"""

import asyncio
import contextlib
import copy
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import pybullet as p
import pybullet_data
import requests
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND_DIR))
import poc_ollama_pybullet as poc  # noqa: E402
import nl_parser  # noqa: E402
import world as world_mod  # noqa: E402
from mobile import Vehicle, all_links  # noqa: E402
import arm as arm_mod  # noqa: E402
import gripper as gripper_mod  # noqa: E402
import llm  # noqa: E402
import skills  # noqa: E402
import world_ops  # noqa: E402

llm.load_env()

UPLOAD_DIR = BACKEND_DIR / "uploads"
SAMPLES_DIR = BACKEND_DIR / "samples"
UPLOAD_DIR.mkdir(exist_ok=True)
PYBULLET_DATA = Path(pybullet_data.getDataPath())
BUILTIN = {
    "default": (PYBULLET_DATA / "kuka_iiwa" / "model.urdf", "KUKA iiwa arm", "/files/default/kuka_iiwa/model.urdf", "/files/default"),
    "rover": (SAMPLES_DIR / "rover.urdf", "Sample rover", "/files/samples/rover.urdf", "/files/samples"),
}

# "localhost" can stall on Windows (IPv6 first); talk to Ollama over IPv4 directly.
OLLAMA_BASE = "http://127.0.0.1:11434"
poc.OLLAMA_API_GENERATE = OLLAMA_BASE + "/api/generate"

MOBILE_PRIMS = ("drive", "move", "turn", "avoid_obstacles", "wander", "explore", "go_to", "face")
ARM_PRIMS = ("set_joints", "move_ee")
GRIP_PRIMS = ("grasp", "release")


def ollama_available() -> bool:
    try:
        return requests.get(OLLAMA_BASE + "/api/tags", timeout=0.6).status_code == 200
    except requests.RequestException:
        return False


@contextlib.contextmanager
def capture_native_output():
    """Capture what PyBullet's C++ code prints (fd 1/2) so load failures can say why."""
    buf = tempfile.TemporaryFile(mode="w+b")
    saved = [os.dup(1), os.dup(2)]
    try:
        sys.stdout.flush()
        os.dup2(buf.fileno(), 1)
        os.dup2(buf.fileno(), 2)
        yield lambda: (buf.seek(0), buf.read().decode("utf-8", "replace"))[1]
    finally:
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])


def native_error_summary(text: str) -> str:
    lines = [re.sub(r"^b3\w+\[[^\]]*\]:\s*", "", l.strip()) for l in text.splitlines()]
    lines = [l for l in lines if l and "build time" not in l]
    return " | ".join(lines[-4:])[:400]


class Session:
    """Owns the single PyBullet world, its physics thread and its plan worker."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        p.connect(p.DIRECT)
        self.robot_id: Optional[int] = None
        self.joints: List[Dict] = []
        self.vehicle: Optional[Vehicle] = None
        self.queue: deque = deque()
        self.stop_event: Optional[threading.Event] = None
        self.threads: List[threading.Thread] = []
        self.info: Dict = {}
        self.active = False
        self.world: List[Dict] = []
        self.world_ids: List[int] = []
        self.world_body: Dict[str, int] = {}  # object id -> PyBullet body id
        self.arm_info: Dict = {}
        self.gripper: Optional[Dict] = None
        self.history: List[Dict] = []
        self._urdf_path: Optional[Path] = None

    # ---- threads ---------------------------------------------------------
    def _shutdown_threads(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        for t in self.threads:
            t.join(timeout=3.0)
        self.threads = []
        self.active = False

    def _start_threads(self) -> None:
        self.queue = deque()
        self.stop_event = threading.Event()
        phys = threading.Thread(target=poc._physics_loop, args=(self.stop_event,), daemon=True)
        work = threading.Thread(
            target=self._worker, args=(self.robot_id, self.joints, self.queue, self.stop_event), daemon=True
        )
        phys.start()
        work.start()
        self.threads = [phys, work]

    def _worker(self, robot_id: int, joints: List[Dict], queue: deque, stop_event: threading.Event) -> None:
        capabilities = poc.analyze_capabilities(robot_id, joints)
        while not stop_event.is_set():
            if len(queue) == 0:
                time.sleep(0.01)
                continue
            item = queue.popleft()
            if isinstance(item, dict) and "plan" in item:
                plan_items, repeat = item.get("plan") or [], bool(item.get("repeat", False))
            elif isinstance(item, list):
                plan_items, repeat = item, False
            else:
                plan_items, repeat = [item], False
            if not plan_items:
                continue
            self.active = True
            try:
                poc.execute_plan(
                    robot_id, joints, plan_items, capabilities=capabilities,
                    stop_event=stop_event, queue=queue, step_physics=False, repeat=repeat, announce=True,
                )
            except Exception as e:  # keep the worker alive
                print("Plan execution error:", e)
            finally:
                self.active = False

    # ---- world -----------------------------------------------------------
    def _clear_world(self) -> None:
        for bid in self.world_ids:
            try:
                p.removeBody(bid)
            except Exception:
                pass
        self.world_ids = []
        self.world_body = {}

    def _rebuild_world(self) -> None:
        self._clear_world()
        for obj in self.world:
            try:
                bid = world_mod.create_body(obj)
                self.world_ids.append(bid)
                self.world_body[obj.get("id", "")] = bid
            except Exception as e:
                print("Skipping bad world object:", obj.get("id"), e)

    def set_world(self, objects: List[Dict]) -> None:
        with self.lock:
            self.world = objects
            self._rebuild_world()

    # ---- robot -----------------------------------------------------------
    def _build_world(self, urdf_path: Path) -> None:
        p.resetSimulation()
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        plane = p.loadURDF("plane.urdf")
        p.changeDynamics(plane, -1, lateralFriction=1.0)
        self.world_ids = []  # resetSimulation removed them
        self.world_body = {}

        # Load free-floating first: if it has wheels it stays that way, otherwise pin the base (arms).
        rid = p.loadURDF(str(urdf_path), useFixedBase=False)
        joints = poc.introspect_joints(rid)
        vehicle = Vehicle.detect(rid, joints)
        if vehicle is not None:
            info = p.getDynamicsInfo(rid, -1)
            p.resetBasePositionAndOrientation(rid, [info[3][0], info[3][1], info[3][2] + vehicle.spawn_lift], info[4])
        else:
            p.removeBody(rid)
            rid = p.loadURDF(str(urdf_path), useFixedBase=True)
            joints = poc.introspect_joints(rid)
        for link in all_links(rid):
            p.setCollisionFilterGroupMask(rid, link, 4, -1)
            if link >= 0 and re.search(r"finger|gripper|claw|jaw|pad", p.getJointInfo(rid, link)[12].decode("utf-8", "ignore").lower()):
                p.changeDynamics(rid, link, lateralFriction=1.5)  # grippers need grip  # robot: group 4, so range rays ignore it
        self.robot_id, self.joints, self.vehicle = rid, joints, vehicle
        self.arm_info = arm_mod.geometry(rid, joints) if vehicle is None else {}
        self.gripper = gripper_mod.find(rid, joints)
        self.history = []
        self._rebuild_world()

    def load(self, urdf_path: Path, info: Dict) -> Dict:
        with self.lock:
            self._shutdown_threads()
            try:
                with capture_native_output() as read_native:
                    try:
                        self._build_world(urdf_path)
                    except Exception as e:
                        detail = native_error_summary(read_native())
                        raise RuntimeError(f"{e} ({detail})" if detail else str(e)) from e
            except Exception:
                # Leave the session usable: fall back to the default robot.
                self._build_world(BUILTIN["default"][0])
                self._urdf_path = BUILTIN["default"][0]
                self.info = self._decorate(builtin_info("default"))
                self._start_threads()
                raise
            self._urdf_path = urdf_path
            self.info = self._decorate(info)
            self._start_threads()
            return self.info

    def _decorate(self, info: Dict) -> Dict:
        return {
            **info,
            "joints": self.joints,
            "mobile": self.vehicle is not None,
            "wheels": [w["name"] for w in self.vehicle.wheels] if self.vehicle else [],
        }

    def reload(self) -> Dict:
        if self._urdf_path is None:
            raise RuntimeError("No robot loaded")
        keep = ("source", "name", "urdf_url", "root_url")
        return self.load(self._urdf_path, {k: self.info[k] for k in keep})

    def stop(self) -> None:
        self.queue.append({"plan": [], "repeat": False})

    def snapshot(self) -> Dict:
        with self.lock:
            if self.robot_id is None:
                return {"joints": {}, "queued": 0, "active": False}
            try:
                positions = {}
                for j in self.joints:
                    if j["type"] != "fixed":
                        positions[j["name"]] = round(float(p.getJointState(self.robot_id, j["index"])[0]), 5)
                pending = any(isinstance(i, dict) and i.get("plan") for i in self.queue)
                snap: Dict = {"joints": positions, "queued": len(self.queue), "active": bool(self.active or pending)}
                dyn = {}
                for o in self.world:
                    bid = self.world_body.get(o.get("id", ""))
                    if o.get("dynamic") and bid is not None:
                        pos, orn = p.getBasePositionAndOrientation(bid)
                        dyn[o["id"]] = [round(c, 3) for c in pos] + [round(c, 4) for c in orn]
                if dyn:
                    snap["objects"] = dyn
                if self.vehicle:
                    snap["base"] = self.vehicle.pose()
                    snap["sensor"] = self.vehicle.scan()
                return snap
            except Exception:
                return {"joints": {}, "queued": 0, "active": False}


def builtin_info(source: str) -> Dict:
    _, name, urdf_url, root_url = BUILTIN[source]
    return {"source": source, "name": name, "urdf_url": urdf_url, "root_url": root_url}


session = Session()

# The PoC's wheel driving is unit-less and its obstacle ray hits the robot itself. Route wheeled
# primitives and obstacle checks through the vehicle model instead (also inside conditionals).
_orig_execute_action = poc.execute_action
_orig_detect_obstacle = poc.detect_obstacle_ahead


def _dispatch_action(robot_id, joints, action, capabilities=None, stop_event=None, queue=None, step_physics=False):
    vehicle = session.vehicle
    if vehicle is not None and isinstance(action, dict) and action.get("primitive") in MOBILE_PRIMS:
        return vehicle.run(action, stop_event, queue)
    if isinstance(action, dict) and action.get("primitive") in GRIP_PRIMS and session.gripper:
        return gripper_mod.run(action, robot_id, joints, vehicle, session.gripper, stop_event, queue)
    if isinstance(action, dict) and action.get("primitive") in ARM_PRIMS:
        return arm_mod.run(action, robot_id, joints, stop_event, queue)
    if isinstance(action, dict) and action.get("primitive") == "stop":
        return False
    return _orig_execute_action(robot_id, joints, action, capabilities, stop_event, queue, step_physics)


def _detect_obstacle(robot_id, distance=0.6, height=0.2):
    vehicle = session.vehicle
    return vehicle.front_range() if vehicle is not None else _orig_detect_obstacle(robot_id, distance, height)


poc.execute_action = _dispatch_action
poc.detect_obstacle_ahead = _detect_obstacle

session.load(BUILTIN["default"][0], builtin_info("default"))


# ---- upload helpers ------------------------------------------------------
def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if dest_resolved not in target.parents and target != dest_resolved:
            raise HTTPException(400, f"Unsafe path in zip: {member.filename}")
    zf.extractall(dest)


def _depth_sorted(paths: List[Path], folder: Path) -> List[Path]:
    return sorted(paths, key=lambda f: (len(f.relative_to(folder).parts), str(f)))


def _find_urdf(folder: Path) -> Optional[Path]:
    urdfs = _depth_sorted(list(folder.rglob("*.urdf")), folder)
    return urdfs[0] if urdfs else None


def _find_xacro(folder: Path) -> Optional[Path]:
    candidates = [f for f in folder.rglob("*.xacro") if "<robot" in f.read_text(errors="ignore")]
    if not candidates:
        return None
    # Prefer a top-level file: one that no other xacro file includes.
    texts = {f: f.read_text(errors="ignore") for f in candidates}
    top = [f for f in candidates if not any(f.name in t for g, t in texts.items() if g != f and "xacro:include" in t)]
    return _depth_sorted(top or candidates, folder)[0]


def _package_dir(folder: Path, pkg: str) -> Path:
    matches = _depth_sorted([d for d in folder.rglob(pkg) if d.is_dir()], folder)
    return matches[0] if matches else folder


def _resolve_find_macros(folder: Path) -> None:
    """Replace ROS-only `$(find pkg)` with real paths so xacro can run without ROS."""
    for f in list(folder.rglob("*.xacro")) + list(folder.rglob("*.urdf")):
        text = f.read_text(errors="ignore")
        new = re.sub(r"\$\(find\s+([^)\s]+)\)", lambda m: _package_dir(folder, m.group(1)).as_posix(), text)
        if new != text:
            f.write_text(new)


def _fix_package_uris(urdf: Path, folder: Path) -> None:
    """PyBullet and the browser can't resolve package:// URIs; rewrite them as relative paths."""
    text = urdf.read_text(errors="ignore")

    def repl(m: re.Match) -> str:
        target = _package_dir(folder, m.group(1)) / m.group(2)
        return Path(os.path.relpath(target, urdf.parent)).as_posix()

    new = re.sub(r"package://([^/\"']+)/([^\"']+)", repl, text)
    if new != text:
        urdf.write_text(new)


def _resolve_mesh(name: str, urdf: Path, folder: Path) -> Optional[str]:
    """Find a mesh file however the URDF spells it (relative, absolute, file://, package://) and
    return its path relative to the URDF, or None if it isn't in the upload."""
    n = name.strip()
    if n.startswith("file://"):
        n = n[len("file://"):]
        if re.match(r"^/[A-Za-z]:", n):  # file:///C:/...
            n = n[1:]
    m = re.match(r"package://[^/]+/(.*)", n)
    if m:
        n = m.group(1)
    candidates = [Path(n), urdf.parent / n, folder / n]
    for c in candidates:
        try:
            if c.is_file():
                return Path(os.path.relpath(c, urdf.parent)).as_posix()
        except OSError:
            pass
    base = Path(n.replace("\\", "/")).name
    if base:
        found = _depth_sorted([f for f in folder.rglob(base) if f.is_file()], folder)
        if found:
            return Path(os.path.relpath(found[0], urdf.parent)).as_posix()
    return None


def _replace_missing_meshes(urdf: Path, folder: Path) -> List[str]:
    """Point mesh references at the files that actually exist in the upload. PyBullet refuses a whole URDF
    if any mesh is missing, so swap missing ones for small placeholder boxes and report them."""
    try:
        tree = ET.parse(urdf)
    except ET.ParseError:
        return []
    missing: List[str] = []
    changed = False
    for geometry in tree.getroot().iter("geometry"):
        mesh = geometry.find("mesh")
        if mesh is None:
            continue
        name = mesh.get("filename", "")
        if not name or name.startswith(("http://", "https://")):
            continue
        resolved = _resolve_mesh(name, urdf, folder)
        if resolved is not None:
            if resolved != name:
                mesh.set("filename", resolved)
                changed = True
            continue
        missing.append(Path(name.replace("\\", "/")).name)
        geometry.remove(mesh)
        ET.SubElement(geometry, "box", size="0.1 0.1 0.1")
        changed = True
    if changed:
        tree.write(urdf, encoding="unicode", xml_declaration=True)
    return missing


def _ensure_collisions(urdf: Path) -> int:
    """Hand-made URDFs often define <visual> but no <collision>; PyBullet then treats those parts as ghosts
    that pass through everything. Give every such link a collision shape copied from its visual."""
    try:
        tree = ET.parse(urdf)
    except ET.ParseError:
        return 0
    added = 0
    for link in tree.getroot().iter("link"):
        if link.find("collision") is not None:
            continue
        for vis in link.findall("visual"):
            geom = vis.find("geometry")
            if geom is None:
                continue
            col = ET.SubElement(link, "collision")
            origin = vis.find("origin")
            if origin is not None:
                col.append(copy.deepcopy(origin))
            col.append(copy.deepcopy(geom))
            added += 1
    if added:
        tree.write(urdf, encoding="unicode", xml_declaration=True)
    return added


def _convert_xacro(xacro_path: Path, folder: Path) -> Path:
    try:
        import xacro
    except ImportError:
        raise HTTPException(500, 'xacro support is missing. Run: py -3.13 -m pip install xacro')
    _resolve_find_macros(folder)
    try:
        doc = xacro.process_file(str(xacro_path))
        xml = doc.toprettyxml(indent="  ")
    except BaseException as e:  # xacro reports some failures via SystemExit
        raise HTTPException(422, f"Couldn't expand {xacro_path.name}: {e}")
    stem = xacro_path.name[: -len(".xacro")]
    out = xacro_path.with_name(stem if stem.endswith(".urdf") else stem + ".urdf")
    if out.exists():
        out = xacro_path.with_name(stem.removesuffix(".urdf") + ".generated.urdf")
    out.write_text(xml)
    return out


def _upload_info(upload_id: str, urdf: Path) -> Dict:
    folder = UPLOAD_DIR / upload_id
    rel = urdf.relative_to(folder).as_posix()
    return {
        "source": upload_id,
        "name": urdf.name.split(".")[0],
        "urdf_url": f"/files/uploads/{upload_id}/{rel}",
        "root_url": f"/files/uploads/{upload_id}",
    }


app = FastAPI(title="NL-Robot backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/files/default", StaticFiles(directory=str(PYBULLET_DATA)), name="default-files")
app.mount("/files/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="sample-files")
app.mount("/files/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="upload-files")


@app.get("/api/health")
def health() -> Dict:
    return {"ok": True, "ollama": ollama_available(), "model": poc.MODEL_NAME, "llm": llm.status(), "robot": session.info}


class SelectBody(BaseModel):
    source: str = "default"


@app.post("/api/robot/select")
def select_robot(body: SelectBody) -> Dict:
    if body.source in BUILTIN:
        return session.load(BUILTIN[body.source][0], builtin_info(body.source))
    if not re.fullmatch(r"[0-9a-f]{12}", body.source):
        raise HTTPException(400, "Bad robot id")
    folder = UPLOAD_DIR / body.source
    urdf = _find_urdf(folder) if folder.is_dir() else None
    if urdf is None:
        raise HTTPException(404, "Uploaded robot not found; upload it again.")
    _ensure_collisions(urdf)  # also repairs robots uploaded before this existed
    try:
        return session.load(urdf, _upload_info(body.source, urdf))
    except Exception as e:
        raise HTTPException(422, f"PyBullet could not load this URDF: {e}")


def _store_and_load(named_files: List[tuple]) -> Dict:
    upload_id = uuid.uuid4().hex[:12]
    folder = UPLOAD_DIR / upload_id
    folder.mkdir(parents=True)
    try:
        for name, data in named_files:
            if name.lower().endswith(".zip"):
                zpath = folder / "_upload.zip"
                zpath.write_bytes(data)
                with zipfile.ZipFile(zpath) as zf:
                    _safe_extract(zf, folder)
                zpath.unlink()
            else:
                # Keep the client-supplied relative path but never escape the folder.
                rel = Path(*[part for part in Path(name.replace("\\", "/")).parts if part not in ("..", "/", "")])
                target = folder / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

        urdf = _find_urdf(folder)
        if urdf is None:
            xacro_file = _find_xacro(folder)
            if xacro_file is None:
                raise HTTPException(400, "No .urdf or .xacro file found in the upload.")
            urdf = _convert_xacro(xacro_file, folder)
        _fix_package_uris(urdf, folder)
        missing = _replace_missing_meshes(urdf, folder)
        _ensure_collisions(urdf)
        info = _upload_info(upload_id, urdf)
        if missing:
            shown = ", ".join(sorted(set(missing))[:3])
            info["warnings"] = [
                f"{len(set(missing))} mesh file(s) weren't uploaded (e.g. {shown}), so those parts show as small placeholder "
                "boxes. Upload the .zip or folder that includes the meshes folder for the real geometry."
            ]
        try:
            return session.load(urdf, info)
        except Exception as e:
            raise HTTPException(422, f"PyBullet could not load this robot: {e}")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.post("/api/robot/upload")
async def upload_robot(files: List[UploadFile] = File(...)) -> Dict:
    named = [(f.filename or "file", await f.read()) for f in files]
    return await run_in_threadpool(_store_and_load, named)


@app.post("/api/robot/reset")
def reset_robot() -> Dict:
    return session.reload()


class WorldBody(BaseModel):
    objects: List[Dict]


@app.put("/api/world")
def put_world(body: WorldBody) -> Dict:
    session.set_world(body.objects)
    return {"ok": True, "count": len(body.objects)}


class CommandBody(BaseModel):
    text: str
    mode: str = "robot"  # "map" = only build/edit the world, never move the robot


def describe_state() -> Dict:
    """Everything the AI needs to know about the robot and the world (compact JSON)."""
    s = session
    veh = s.vehicle
    r = lambda v: round(float(v), 2)  # noqa: E731
    robot: Dict = {"name": s.info.get("name"), "type": "wheeled" if veh else "arm/articulated"}
    if veh:
        pos, yaw = veh.position(), veh.yaw()
        robot.update(
            pose={"x": r(pos[0]), "y": r(pos[1]), "heading_deg": r(math.degrees(yaw))},
            footprint_m=[r(2 * veh.hl), r(2 * veh.hw)],
            wheels=len(veh.wheels),
            sensors={"range_sensor": "360-degree lidar-style, 6 m", "front_clearance_m": r(veh.scan()["front"])},
        )
        driven = {w["name"] for w in veh.wheels}
    else:
        driven = set()
        ee = arm_mod.current_ee(s.robot_id, s.joints)
        robot.update(
            base_position=[0, 0, 0],
            end_effector=[r(c) for c in ee] if ee else None,
            home_end_effector=s.arm_info.get("ee_position"),
            reach_m=s.arm_info.get("reach"),
        )
    joints = []
    for j in arm_mod.movable(s.joints):
        if j["name"] in driven:
            continue
        lo, hi = arm_mod._limits(j)
        now = p.getJointState(s.robot_id, j["index"])[0]
        if j["type"] == "prismatic":  # sliding joint (lift, gripper finger): metres
            joints.append({"name": j["name"], "type": "prismatic", "unit": "m", "min": r(lo), "max": r(hi), "now": r(now)})
        else:
            joints.append({
                "name": j["name"], "type": j["type"], "unit": "deg",
                "min": r(math.degrees(lo)), "max": r(math.degrees(hi)), "now": r(math.degrees(now)),
            })
    robot["joints"] = joints
    if s.gripper:
        robot["gripper"] = {
            "joints": s.gripper["joints"], "max_opening_m": s.gripper["opening"], "fingers_reach_ahead_m": s.gripper["tip_ahead"],
            "note": "use the grasp and release skills; they handle approach and jaw positions",
        }

    objects = []
    for o in s.world:
        cz = o["z"] + o["h"] / 2
        entry = {
            "name": o["name"], "kind": o["kind"], "center": [r(o["x"]), r(o["y"]), r(cz)],
            "size": [r(o["w"]), r(o["d"]), r(o["h"])], "yaw_deg": r(o["yaw"]), "dynamic": bool(o.get("dynamic")),
        }
        if not veh:  # where an arm would strike the object: its surface facing the base
            dist = math.hypot(o["x"], o["y"]) or 1.0
            rad = max(o["w"], o["d"]) / 2
            entry["hit_point"] = [r(o["x"] - o["x"] / dist * rad), r(o["y"] - o["y"] / dist * rad), r(cz)]
        objects.append(entry)
    return {"robot": robot, "objects": objects, "recent_commands": s.history[-6:]}


MAP_DIRECTIVE = (
    "MAP BUILDING MODE. Only build or edit the world; set steps to [] and never move the robot. Build what the user describes "
    "as completely and as well as you can (up to about 70 objects; merge walls that run in a straight line into single long boxes). "
    "Unless the user says to add to or change the existing map, set world.clear=true and rebuild from scratch. Keep about 1.5 m around "
    "the origin free for the robot, and for mazes guarantee a path from the start to an exit. Use the robot footprint in STATE to size "
    "corridors and doorways so the robot fits.\nUser request: "
)


@app.post("/api/command")
def command(body: CommandBody) -> Dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty command")
    map_mode = body.mode == "map"

    warnings: List[str] = []
    actions: List[Dict] = []
    reply, source, repeat, world_changed, llm_error = None, None, False, False, None

    result = None
    try:
        result = llm.interpret(
            describe_state(), MAP_DIRECTIVE + text if map_mode else text,
            effort=os.environ.get("NL_ROBOT_MAP_EFFORT", "low") if map_mode else None,
        )
    except llm.LLMError as e:
        llm_error = str(e)

    if result is not None:
        plan, source = result["plan"], result["provider"]
        ops = plan.get("world")
        if isinstance(ops, dict) and any(ops.get(k) for k in ("clear", "remove", "add", "update")):
            new_world, w = world_ops.apply_ops(session.world, ops)
            warnings += w
            session.set_world(new_world)
            world_changed = True
        actions, w = skills.normalize(
            plan.get("steps") or [], session.vehicle is not None, session.joints, session.world,
            {w["name"] for w in session.vehicle.wheels} if session.vehicle else set(),
            has_gripper=session.gripper is not None,
        )
        warnings += w
        reply = str(plan.get("reply") or "").strip() or None
        repeat = bool(plan.get("repeat"))
        if map_mode:
            actions, repeat = [], False  # the map tab never moves the robot
    elif map_mode:
        why = f" ({llm_error})" if llm_error else ""
        raise HTTPException(422, "Building maps needs the AI connected (add ANTHROPIC_API_KEY in backend/.env)." + why)
    else:
        # No AI available (or it failed): fall back to the built-in phrase parser.
        joints, robot_id = session.joints, session.robot_id
        envelope, source = None, "local-parser"
        if session.vehicle is not None:
            envelope = nl_parser.parse(text)
        if envelope is None:
            envelope = poc.parse_compound_sequence(joints, text) or poc.local_simple_planner(joints, text)
        if not envelope or not envelope.get("plan"):
            why = f" ({llm_error})" if llm_error else ""
            hint = "" if llm.status()["provider"] else " Connect an AI model (see backend/README) so I can understand free-form requests."
            raise HTTPException(422, "I couldn't work out what to do with that." + why + hint)
        actions, repeat = envelope["plan"], bool(envelope.get("repeat")) or poc._user_wants_repeat(text)

    if not actions and not world_changed:
        raise HTTPException(422, (reply + " " if reply else "") + "Nothing runnable came out of that." + (" " + " ".join(warnings) if warnings else ""))

    if actions:
        session.queue.append({"plan": actions, "repeat": repeat})
    if not map_mode:
        session.history.append({"user": text, "reply": reply, "steps": [a["primitive"] for a in actions]})
    return {
        "ok": True, "source": source, "reply": reply, "plan": actions, "repeat": repeat,
        "world": session.world if world_changed else None, "warnings": warnings,
        "llm": llm.status(), "llm_error": llm_error,
    }


@app.post("/api/stop")
def stop() -> Dict:
    session.stop()
    return {"ok": True}


@app.websocket("/ws")
async def ws_state(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(json.dumps(await run_in_threadpool(session.snapshot)))
            await asyncio.sleep(1 / 30)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        pass
