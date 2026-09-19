"""FastAPI surface. Every route keeps the exact shape the existing frontend expects.

The interesting part is what is NOT here: the LLM call, plan validation and world editing
are `llm.py`, `skills.py` and `world_ops.py` reused unchanged from the PyBullet product.
Only the simulator behind `session` is new.
"""

import math
import os
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket, WebSocketDisconnect

import asyncio
import json

import llm
import skills
import world_ops
from session import Session

llm.load_env()

MODELS_DIR = Path("/sim/models")

app = FastAPI(title="NL-Robot-GZ bridge")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
if MODELS_DIR.exists():
    app.mount("/files", StaticFiles(directory=str(MODELS_DIR)), name="model-files")

session = Session()


def ollama_available() -> bool:
    try:
        import requests

        return requests.get(llm.OLLAMA_BASE + "/api/tags", timeout=0.6).status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------- state for the LLM

MAP_DIRECTIVE = (
    "MAP BUILDING MODE. Only build or edit the world; set steps to [] and never move the robot. Build what the user describes "
    "as completely and as well as you can (up to about 70 objects; merge walls that run in a straight line into single long boxes). "
    "Unless the user says to add to or change the existing map, set world.clear=true and rebuild from scratch. Scale EVERYTHING to this "
    "robot using STATE robot.size_m and robot.scale_guide (corridor widths, wall height and thickness, obstacle sizes, distances, "
    "clear start area). For mazes guarantee a path from the start to an exit that the robot physically fits through.\nUser request: "
)


def describe_state() -> Dict:
    """Everything the AI needs about the robot and the world (compact JSON).

    Ported from the PyBullet server: the scale_guide maths is unchanged, only the two
    simulator reads (joint positions, end-effector) now come from ROS and forward
    kinematics instead of PyBullet.
    """
    r = lambda v: round(float(v), 2)  # noqa: E731
    vehicle = session.vehicle
    position, yaw = vehicle.position(), vehicle.yaw()
    live = session.state.snapshot_joints()

    robot: Dict = {
        "name": session.info.get("name"),
        "type": "wheeled",
        "pose": {"x": r(position[0]), "y": r(position[1]), "heading_deg": r(math.degrees(yaw))},
        "footprint_m": [r(2 * vehicle.hl), r(2 * vehicle.hw)],
        "wheels": len(vehicle.wheels),
        "sensors": {
            "range_sensor": "360-degree lidar-style, 8 m",
            "front_clearance_m": r(vehicle.scan()["front"]),
        },
        "end_effector": [r(c) for c in session.kin.fk(live)],
        "reach_m": r(session.kin.reach),
    }

    joints = []
    for spec in session.joints:
        name = spec["name"]
        if name in session.wheel_names or spec["type"] == "fixed":
            continue
        if spec["lower_limit"] is None or spec["upper_limit"] is None:
            continue
        now = live.get(name, 0.0)
        if spec["type"] == "prismatic":
            joints.append({"name": name, "type": "prismatic", "unit": "m",
                           "min": r(spec["lower_limit"]), "max": r(spec["upper_limit"]), "now": r(now)})
        else:
            joints.append({"name": name, "type": spec["type"], "unit": "deg",
                           "min": r(math.degrees(spec["lower_limit"])),
                           "max": r(math.degrees(spec["upper_limit"])),
                           "now": r(math.degrees(now))})
    robot["joints"] = joints

    length, width, height = 2 * vehicle.hl, 2 * vehicle.hw, vehicle.height
    robot["size_m"] = [r(length), r(width), r(height)]
    robot["scale_guide"] = {
        "unit_m": r(width),
        "min_corridor_width_m": r(max(width + 1.0, 1.8 * width)),
        "min_turnaround_space_m": r(2 * vehicle.radius * 1.2),
        "wall_height_m": r(max(1.0, 1.3 * height)),
        "wall_thickness_m": r(max(0.2, 0.1 * width)),
        "obstacle_sizes_m": {"small": r(0.5 * width), "medium": r(width), "large": r(2 * width)},
        "clear_start_radius_m": r(vehicle.radius * 1.5 + 0.5),
        "typical_distance_ahead_m": r(max(4.0, 4 * length)),
        "arena_half_extent_m": r(max(12.0, 8 * length)),
    }
    if session.gripper:
        robot["scale_guide"]["graspable_size_max_m"] = r(0.8 * session.gripper["opening"])
        robot["gripper"] = {
            "joints": session.gripper["joints"],
            "max_opening_m": r(session.gripper["opening"]),
            "fingers_reach_ahead_m": r(session.gripper["tip_ahead"]),
            "note": "use the grasp and release skills; they handle approach and jaw positions",
        }

    objects = []
    for obj in session.world_snapshot():
        objects.append({
            "name": obj["name"], "kind": obj["kind"],
            "center": [r(obj["x"]), r(obj["y"]), r(obj["z"] + obj["h"] / 2)],
            "size": [r(obj["w"]), r(obj["d"]), r(obj["h"])],
            "yaw_deg": r(obj.get("yaw", 0)), "dynamic": bool(obj.get("dynamic")),
        })
    return {"robot": robot, "objects": objects, "recent_commands": session.history[-6:]}


# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> Dict:
    status = llm.status()
    return {
        "ok": True,
        "ollama": ollama_available(),
        "model": status.get("model") or "",
        "robot": session.robot_info(),
    }


class SelectBody(BaseModel):
    source: str


@app.post("/api/robot/select")
def select_robot(body: SelectBody) -> Dict:
    # One robot is loaded per container (NLROBOT_ROBOT). 'default' is accepted because
    # the UI hardcodes it -- lib/sims.ts seeds every new sim with robotSource 'default'.
    info = session.robot_info()
    known = ("default", "rover", "nlbot", "tb3", session.info["source"])
    if body.source not in known:
        info["warnings"] = [f"Unknown robot '{body.source}'; kept {session.model.name}."]
    return info


@app.post("/api/robot/upload")
async def upload_robot(files: List[UploadFile] = File(...)) -> Dict:
    """Run the uploaded robot through the same converter that imported the TurtleBot3.

    The pipeline strips Gazebo-Classic plugins, retargets ros2_control to the sim,
    converts sensors to Fortress naming, and reports every sensor it found. Activating
    the robot needs a container restart (the controller stack is instantiated at boot),
    so the response says exactly how.
    """
    import subprocess
    import sys
    import uuid

    sys.path.insert(0, "/sim/tools")
    upload_id = "upload_" + uuid.uuid4().hex[:8]
    raw_dir = Path("/sim/models") / upload_id / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    urdf_path = None
    for f in files:
        name = Path(f.filename or "file").name
        dest = raw_dir / name
        dest.write_bytes(await f.read())
        if name.endswith(".xacro"):
            converted = raw_dir / (name.rsplit(".", 1)[0] + ".converted.urdf")
            done = subprocess.run(["xacro", str(dest)], capture_output=True, text=True)
            if done.returncode == 0:
                converted.write_text(done.stdout)
                urdf_path = converted
            else:
                raise HTTPException(422, f"xacro failed: {done.stderr[:300]}")
        elif name.endswith(".urdf") and urdf_path is None:
            urdf_path = dest
    if urdf_path is None:
        raise HTTPException(422, "No .urdf or .xacro file in the upload.")

    try:
        import import_robot as importer
        import io
        from contextlib import redirect_stdout
        report = io.StringIO()
        with redirect_stdout(report):
            sys.argv = ["import_robot", str(urdf_path), f"/sim/models/{upload_id}", upload_id]
            importer.main()
    except Exception as exc:
        raise HTTPException(422, f"Robot conversion failed: {exc}")

    import robot_model
    uploaded = robot_model.load(f"/sim/models/{upload_id}/{upload_id}.urdf")
    sensor_names = [f"{s['type']} on {s['link']}" for s in uploaded.sensors] or ["none declared"]

    info = session.robot_info()
    info["warnings"] = [
        f"Converted for Gazebo Fortress as '{upload_id}': "
        f"{len(uploaded.movable)} movable joints, wheels {uploaded.wheels or 'none'}, "
        f"sensors: {', '.join(sensor_names)}. "
        f"To drive it, set NLROBOT_ROBOT={upload_id} in docker-compose.yml and restart "
        "(the controller stack is built at boot). Until then the current robot stays active."
    ]
    return info


@app.post("/api/robot/reset")
def reset_robot() -> Dict:
    return session.reset()


class WorldBody(BaseModel):
    objects: List[Dict]


@app.put("/api/world")
def put_world(body: WorldBody) -> Dict:
    session.set_world(body.objects)
    return {"ok": True}


class CommandBody(BaseModel):
    text: str
    mode: str = "robot"


@app.post("/api/command")
def command(body: CommandBody) -> Dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty command")
    map_mode = body.mode == "map"

    warnings: List[str] = []
    actions: List[Dict] = []
    reply = source = None
    repeat = world_changed = False
    llm_error = None

    result = None
    try:
        result = llm.interpret(
            describe_state(),
            MAP_DIRECTIVE + text if map_mode else text,
            effort=os.environ.get("NL_ROBOT_MAP_EFFORT", "low") if map_mode else None,
        )
    except llm.LLMError as exc:
        llm_error = str(exc)

    if result is None:
        detail = "I couldn't work out what to do with that."
        if llm_error:
            detail += f" ({llm_error})"
        if not llm.status().get("provider"):
            detail += " Set ANTHROPIC_API_KEY so the planner can run."
        raise HTTPException(422, detail)

    plan, source = result["plan"], result["provider"]
    ops = plan.get("world")
    if isinstance(ops, dict) and any(ops.get(k) for k in ("clear", "remove", "add", "update")):
        new_world, ops_warnings = world_ops.apply_ops(session.world_snapshot(), ops)
        warnings += ops_warnings
        warnings += session.set_world(new_world)
        world_changed = True

    actions, skill_warnings = skills.normalize(
        plan.get("steps") or [],
        True,
        session.joints,
        session.world_snapshot(),
        session.wheel_names,
        has_gripper=bool(session.gripper),
    )
    warnings += skill_warnings
    reply = str(plan.get("reply") or "").strip() or None
    repeat = bool(plan.get("repeat"))
    if map_mode:
        actions, repeat = [], False

    if not actions and not world_changed:
        raise HTTPException(
            422,
            (reply + " " if reply else "") + "Nothing runnable came out of that."
            + (" " + " ".join(warnings) if warnings else ""),
        )

    path = session.vehicle.preview(actions) if actions and not map_mode else []
    if actions:
        session.submit(actions, repeat)
    if not map_mode:
        session.history.append(
            {"user": text, "reply": reply, "steps": [a["primitive"] for a in actions]}
        )

    return {
        "ok": True, "source": source, "reply": reply, "plan": actions, "repeat": repeat,
        "world": session.world_snapshot() if world_changed else None,
        "warnings": warnings, "llm": llm.status(), "llm_error": llm_error, "path": path,
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
            frame = await run_in_threadpool(session.snapshot)
            await websocket.send_text(json.dumps(frame))
            await asyncio.sleep(1 / 30)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        pass
