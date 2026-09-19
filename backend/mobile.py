"""Wheeled-robot kinematics, a 360-degree range sensor, and reactive navigation.

Arms are driven joint-by-joint. Wheeled robots need different maths: wheel speeds come from a desired
forward speed `v` and yaw rate `w` (differential drive), and behaviours react to what the range sensor sees.

The sensor is a lidar-style ring of rays cast from the middle of the robot's footprint. Distances are turned
into *clearances* (gap between the robot's body and the obstacle along each ray) so behaviours can reason about
"will I fit / will I hit" instead of raw ranges.
"""

import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import pybullet as p

import poc_ollama_pybullet as poc

MAX_RANGE = 6.0
N_RAYS = 72  # every 5 degrees
A0 = -math.pi
DA = 2 * math.pi / N_RAYS
DT = 1.0 / 60.0
RAY_MASK = 3  # world bodies are group 1 (dynamic) or 2 (static); the robot is group 4, so rays skip it
FRONT_HALF_ANGLE = math.radians(8)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def base_frame(robot: int):
    """World pose of the URDF base link frame (PyBullet reports the inertial frame)."""
    com_pos, com_orn = p.getBasePositionAndOrientation(robot)
    info = p.getDynamicsInfo(robot, -1)
    inv_pos, inv_orn = p.invertTransform(info[3], info[4])
    return p.multiplyTransforms(com_pos, com_orn, inv_pos, inv_orn)


def all_links(robot: int) -> range:
    return range(-1, p.getNumJoints(robot))


class Vehicle:
    def __init__(self, robot: int, joints: List[Dict], wheels: List[Dict]):
        self.robot = robot
        self.wheels = wheels
        lefts = [abs(w["y"]) for w in wheels if w["side"] > 0]
        rights = [abs(w["y"]) for w in wheels if w["side"] < 0]
        self.track = (sum(lefts) / len(lefts) + sum(rights) / len(rights)) if lefts and rights else 0.3
        mass = sum(p.getDynamicsInfo(robot, i)[0] for i in all_links(robot))
        self.force = max(30.0, mass * 4.0)

        lows, highs = [], []
        for i in all_links(robot):
            lo, hi = p.getAABB(robot, i)
            lows.append(lo)
            highs.append(hi)
        bpos, _ = base_frame(robot)
        x_lo, x_hi = min(l[0] for l in lows) - bpos[0], max(h[0] for h in highs) - bpos[0]
        y_lo, y_hi = min(l[1] for l in lows) - bpos[1], max(h[1] for h in highs) - bpos[1]
        min_z, max_z = min(l[2] for l in lows), max(h[2] for h in highs)
        # Footprint rectangle (base frame) and the sensor origin at its centre.
        self.hl, self.hw = max(0.05, (x_hi - x_lo) / 2), max(0.05, (y_hi - y_lo) / 2)
        self.cx, self.cy = (x_hi + x_lo) / 2, (y_hi + y_lo) / 2
        self.radius = math.hypot(self.hl, self.hw)
        # Half-angle of the sector swept by the front corners when moving forward (corner angle + margin).
        self.front_sector = max(math.radians(25), math.atan2(self.hw, self.hl) + 0.17)
        self.ray_heights = [min_z + 0.06 - bpos[2], (min_z + max_z) / 2 - bpos[2]]
        self.spawn_lift = 0.01 - min_z
        self.angles = [A0 + i * DA for i in range(N_RAYS)]
        self.boundary = [self._boundary(a) for a in self.angles]

        driven = {w["index"] for w in wheels}
        for j in joints:
            if j["type"] in ("continuous", "revolute") and j["index"] not in driven:
                # Passive joints (casters etc.) must spin freely instead of holding at zero velocity.
                p.setJointMotorControl2(robot, j["index"], p.VELOCITY_CONTROL, targetVelocity=0, force=0)
        for w in wheels:
            p.changeDynamics(robot, w["index"], lateralFriction=1.2)

    def _boundary(self, a: float) -> float:
        """Distance from the footprint centre to its edge along direction `a` (robot frame)."""
        ca, sa = abs(math.cos(a)), abs(math.sin(a))
        return min(self.hl / ca if ca > 1e-6 else 1e9, self.hw / sa if sa > 1e-6 else 1e9)

    # ---- detection -------------------------------------------------------
    @classmethod
    def detect(cls, robot: int, joints: List[Dict]) -> Optional["Vehicle"]:
        bpos, born = base_frame(robot)
        inv_pos, inv_orn = p.invertTransform(bpos, born)
        named, geometric = [], []
        for j in joints:
            if j["type"] not in ("continuous", "revolute"):
                continue
            n = j["name"].lower()
            if "caster" in n or "steer" in n:
                continue
            ls = p.getLinkState(robot, j["index"], computeForwardKinematics=1)
            axis_w = p.rotateVector(ls[5], p.getJointInfo(robot, j["index"])[13])
            axis_b = p.rotateVector(inv_orn, axis_w)
            pos_b, _ = p.multiplyTransforms(inv_pos, inv_orn, ls[4], [0, 0, 0, 1])
            if abs(axis_b[1]) < 0.8:
                continue
            lo, hi = p.getAABB(robot, j["index"])
            radius = (hi[2] - lo[2]) / 2
            entry = {
                "index": j["index"],
                "name": j["name"],
                "side": 1 if pos_b[1] >= 0 else -1,
                "sign": 1.0 if axis_b[1] > 0 else -1.0,  # spin direction that rolls the robot forward (+x)
                "radius": radius if 0.01 < radius < 2.0 else 0.1,
                "y": pos_b[1],
            }
            if any(k in n for k in ("wheel", "tire", "tyre")):
                named.append(entry)
            elif j["type"] == "continuous":
                geometric.append(entry)
        wheels = named or geometric
        if len(wheels) < 2 or not (any(w["side"] > 0 for w in wheels) and any(w["side"] < 0 for w in wheels)):
            return None
        return cls(robot, joints, wheels)

    # ---- low-level control ----------------------------------------------
    def set_speeds(self, v: float, w: float) -> None:
        """v: forward speed (m/s), w: yaw rate (rad/s, positive = turn left)."""
        for wh in self.wheels:
            side_v = v - wh["side"] * w * self.track / 2
            p.setJointMotorControl2(
                self.robot, wh["index"], p.VELOCITY_CONTROL,
                targetVelocity=wh["sign"] * side_v / wh["radius"], force=self.force,
            )

    def stop(self) -> None:
        self.set_speeds(0.0, 0.0)

    def yaw(self) -> float:
        return p.getEulerFromQuaternion(base_frame(self.robot)[1])[2]

    def position(self):
        return base_frame(self.robot)[0]

    def pose(self) -> Dict:
        pos, orn = base_frame(self.robot)
        return {"pos": [round(c, 4) for c in pos], "quat": [round(c, 5) for c in orn]}

    # ---- range sensor ----------------------------------------------------
    def _origin(self) -> Tuple[List[float], float]:
        bpos, born = base_frame(self.robot)
        yaw = p.getEulerFromQuaternion(born)[2]
        yaw_q = p.getQuaternionFromEuler([0, 0, yaw])
        origin, _ = p.multiplyTransforms(bpos, yaw_q, [self.cx, self.cy, 0], [0, 0, 0, 1])
        return list(origin), yaw

    def _cast(self, idx: List[int], ignore: Optional[Tuple[float, float, float]] = None) -> List[float]:
        """Raw ray distances (from the footprint centre) for the ray indices `idx`."""
        bpos, _ = base_frame(self.robot)
        origin, yaw = self._origin()
        starts, ends = [], []
        for zoff in self.ray_heights:
            o = [origin[0], origin[1], bpos[2] + zoff]
            for i in idx:
                a = yaw + self.angles[i]
                starts.append(o)
                ends.append([o[0] + MAX_RANGE * math.cos(a), o[1] + MAX_RANGE * math.sin(a), o[2]])
        hits = p.rayTestBatch(starts, ends, collisionFilterMask=RAY_MASK)
        n = len(idx)
        out = [MAX_RANGE] * n
        for k, h in enumerate(hits):
            if h[0] < 0:
                continue
            d = h[2] * MAX_RANGE
            if ignore is not None:  # ignore hits on the object we are deliberately approaching
                hx, hy = starts[k][0] + (ends[k][0] - starts[k][0]) * h[2], starts[k][1] + (ends[k][1] - starts[k][1]) * h[2]
                if math.hypot(hx - ignore[0], hy - ignore[1]) <= ignore[2]:
                    continue
            out[k % n] = min(out[k % n], d)
        return out

    def clearances(self, ignore=None) -> List[float]:
        """Free space between the robot's body and the nearest obstacle along each of the N_RAYS directions."""
        raw = self._cast(list(range(N_RAYS)), ignore)
        return self._to_clearance(raw)

    def _to_clearance(self, raw: List[float]) -> List[float]:
        return [MAX_RANGE if d >= MAX_RANGE - 1e-3 else max(0.0, d - b) for d, b in zip(raw, self.boundary)]

    def _window(self, c: List[float], centre: float, half: float) -> float:
        """Smallest clearance among rays within +-half radians of direction `centre` (robot frame)."""
        best = MAX_RANGE
        for a, v in zip(self.angles, c):
            if abs(wrap(a - centre)) <= half and v < best:
                best = v
        return best

    def scan(self) -> Dict:
        raw = self._cast(list(range(N_RAYS)))
        origin, yaw = self._origin()
        bpos, _ = base_frame(self.robot)
        origin[2] = bpos[2] + self.ray_heights[-1]
        c = self._to_clearance(raw)
        return {
            "origin": [round(v, 3) for v in origin],
            "yaw": round(yaw, 4),
            "a0": round(A0, 5),
            "da": round(DA, 5),
            "range": MAX_RANGE,
            "dist": [round(d, 2) for d in raw],
            "front": round(self._window(c, 0.0, FRONT_HALF_ANGLE), 3),
        }

    def front_range(self) -> Optional[float]:
        """Clearance ahead in metres, or None if nothing is in sensor range."""
        d = self._window(self.clearances(), 0.0, FRONT_HALF_ANGLE)
        return d if d < MAX_RANGE - 0.5 else None

    # ---- behaviours ------------------------------------------------------
    def run(self, action: Dict, stop_event, queue: Optional[deque]) -> bool:
        """Execute one wheeled primitive. Returns True if interrupted."""
        prim = action.get("primitive")
        params = action.get("params") or {}
        try:
            if prim in ("drive", "move"):
                return self._drive(params, stop_event, queue)
            if prim == "turn":
                return self._turn(float(params.get("angle_degrees", 90.0)), stop_event, queue)
            if prim == "face":
                return self._face(params, stop_event, queue)
            if prim == "go_to":
                return self._go_to(params, stop_event, queue)
            if prim in ("avoid_obstacles", "wander", "explore"):
                return self._navigate(None, params, stop_event, queue)
            return False
        finally:
            self.stop()

    def _drive(self, params: Dict, stop_event, queue) -> bool:
        speed = params.get("speed")
        v = 0.8 if speed is None or abs(float(speed)) > 2.0 else abs(float(speed))  # PoC plans use unitless speeds (5.0)
        distance = params.get("distance")
        duration = params.get("duration")
        stop_within = params.get("until_front_within", params.get("until_within"))
        safe = params.get("safe", True)
        if distance is None and duration is None and stop_within is None:
            duration = 2.0
        reverse = bool(params.get("reverse")) or (distance is not None and float(distance) < 0)
        limit = abs(float(distance)) if distance is not None else None
        end = time.time() + (float(duration) if duration is not None else 60.0)
        start = self.position()
        centre = math.pi if reverse else 0.0
        while time.time() < end:
            if poc._interrupted(stop_event, queue):
                return True
            v_now = v
            ahead = None
            if stop_within is not None or safe:
                ahead = self._window(self.clearances(), centre, self.front_sector)
            if stop_within is not None and not reverse and ahead is not None and ahead < MAX_RANGE - 0.5:
                if ahead <= float(stop_within):
                    break
                v_now = v * max(0.3, min(1.0, (ahead - float(stop_within)) / 1.0))
            if safe and ahead is not None and ahead < 0.06:
                break  # about to touch something: stop rather than crash
            if limit is not None:
                pos = self.position()
                travelled = math.hypot(pos[0] - start[0], pos[1] - start[1])
                if travelled >= limit - 0.01:
                    break
                v_now = max(0.2, min(v_now, 2.0 * (limit - travelled)))
            self.set_speeds(-v_now if reverse else v_now, 0.0)
            time.sleep(DT)
        return False

    def _turn(self, angle_deg: float, stop_event, queue) -> bool:
        target = math.radians(angle_deg)
        turned, last = 0.0, self.yaw()
        deadline = time.time() + max(8.0, abs(target) * 4.0)
        while time.time() < deadline:
            if poc._interrupted(stop_event, queue):
                return True
            yaw = self.yaw()
            turned += wrap(yaw - last)
            last = yaw
            err = target - turned
            if abs(err) < 0.03:
                break
            w = max(-1.6, min(1.6, 2.5 * err))
            if abs(w) < 0.35:
                w = math.copysign(0.35, err)
            self.set_speeds(0.0, w)
            time.sleep(DT)
        return False

    def _face(self, params: Dict, stop_event, queue) -> bool:
        pos = self.position()
        bearing = wrap(math.atan2(float(params["y"]) - pos[1], float(params["x"]) - pos[0]) - self.yaw())
        return self._turn(math.degrees(bearing), stop_event, queue)

    def _go_to(self, params: Dict, stop_event, queue) -> bool:
        return self._navigate((float(params["x"]), float(params["y"])), params, stop_event, queue)

    def _navigate(self, goal: Optional[Tuple[float, float]], params: Dict, stop_event, queue) -> bool:
        """Reactive navigation: pick the most open direction (biased toward the goal, if any) and drive that way.

        Without a goal this is obstacle-avoiding wandering; it never turns into something it can't fit past.
        """
        v_max = min(1.2, max(0.2, float(params.get("speed", 0.7))))
        stop_d = 0.2 + 0.2 * self.radius  # bigger robots need more room to manoeuvre
        slow_d = stop_d + 0.9
        duration = params.get("duration")
        end = time.time() + (float(duration) if duration is not None else (90.0 if goal else 900.0))
        gap_stop = float(params.get("stop_distance", 0.2))
        target_r = params.get("target_radius")
        ignore = None
        if goal and params.get("target_radius") is not None:
            ignore = (goal[0], goal[1], float(params["target_radius"]) + 0.35)
        last_dir = 0.0
        half_win = 4  # rays each side (+-20 degrees) considered when judging a heading
        while time.time() < end:
            if poc._interrupted(stop_event, queue):
                return True
            c = self.clearances(ignore)
            yaw = self.yaw()
            bearing = 0.0
            if goal:
                origin, _ = self._origin()  # footprint centre, so long robots are measured from their nose
                dist = math.hypot(goal[0] - origin[0], goal[1] - origin[1])
                bearing = wrap(math.atan2(goal[1] - origin[1], goal[0] - origin[0]) - yaw)
                if params.get("grasp_forward") is not None:
                    ref = p.getLinkState(self.robot, int(params["grasp_ref_link"]), computeForwardKinematics=1)[4] if int(params["grasp_ref_link"]) >= 0 else self.position()
                    fwd = (goal[0] - ref[0]) * math.cos(yaw) + (goal[1] - ref[1]) * math.sin(yaw)
                    if fwd <= float(params["grasp_forward"]):
                        break  # the object is now between the fingers
                elif target_r is not None:
                    if dist - self._boundary(bearing) - float(target_r) <= gap_stop:
                        break  # the robot's edge is within stop_distance of the object's surface
                elif dist <= 0.15:
                    break

            best_score, best_i, best_free = -1e9, N_RAYS // 2, 0.0
            for i in range(N_RAYS):
                free = min(c[(i + k) % N_RAYS] for k in range(-half_win, half_win + 1))
                h = self.angles[i]
                score = min(free, 2.5) - 1.3 * abs(wrap(h - bearing)) / math.pi
                if last_dir and h * last_dir > 0:
                    score += 0.25  # hysteresis: keep turning the same way instead of dithering
                if score > best_score:
                    best_score, best_i, best_free = score, i, free
            heading = self.angles[best_i]
            ahead = self._window(c, 0.0, self.front_sector)
            w = max(-1.5, min(1.5, 2.0 * heading))
            if abs(heading) > 0.05:
                last_dir = heading

            if best_free <= stop_d or ahead <= 0.10:
                # Boxed in along the chosen heading: turn on the spot if the body sweep is clear, else back off.
                rot_margin = min(cc - (self.radius - b) for cc, b in zip(c, self.boundary))
                rear = self._window(c, math.pi, self.front_sector)
                spin = math.copysign(1.0, heading if abs(heading) > 0.05 else (last_dir or 1.0))
                if rot_margin >= 0.08:
                    self.set_speeds(0.0, spin * 1.0)  # body sweep is clear: turn on the spot
                elif rear >= 0.30:
                    self.set_speeds(-0.25, 0.0)  # too tight to spin: back off first
                else:
                    self.set_speeds(0.0, spin * 0.5)  # nowhere better to go: creep round slowly
            else:
                v = v_max * max(0.0, min(1.0, (best_free - stop_d) / (slow_d - stop_d))) * max(0.0, math.cos(heading)) ** 2
                if ahead <= 0.10:
                    v = 0.0
                self.set_speeds(max(v, 0.08 if abs(heading) < 0.6 else 0.0), w)
            time.sleep(DT)
        return False
