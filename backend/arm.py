"""Joint-space skills for arms and other articulated robots: set_joints and move_ee (inverse kinematics)."""

import math
import time
from collections import deque
from typing import Dict, List, Optional

import pybullet as p

import poc_ollama_pybullet as poc

DT = 1.0 / 60.0


def movable(joints: List[Dict]) -> List[Dict]:
    return sorted((j for j in joints if j["type"] != "fixed"), key=lambda j: j["index"])


def _limits(j: Dict):
    if j["type"] == "continuous" or j.get("lower_limit") is None or j["upper_limit"] <= j["lower_limit"]:
        return -2 * math.pi, 2 * math.pi
    return j["lower_limit"], j["upper_limit"]


def geometry(robot: int, joints: List[Dict]) -> Dict:
    """End-effector position and a rough reach estimate (sum of link-to-link distances at the rest pose)."""
    mv = movable(joints)
    if not mv:
        return {"ee_link": None, "ee_position": None, "reach": 0.0}
    base, _ = p.getBasePositionAndOrientation(robot)
    pts = [base] + [p.getLinkState(robot, j["index"], computeForwardKinematics=1)[4] for j in mv]
    reach = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    return {"ee_link": mv[-1]["index"], "ee_position": [round(c, 3) for c in pts[-1]], "reach": round(reach, 3)}


def current_ee(robot: int, joints: List[Dict]) -> Optional[List[float]]:
    mv = movable(joints)
    if not mv:
        return None
    return list(p.getLinkState(robot, mv[-1]["index"], computeForwardKinematics=1)[4])


def _interpolate(robot: int, targets: Dict[int, float], duration: float, stop_event, queue: Optional[deque]) -> bool:
    start = {idx: p.getJointState(robot, idx)[0] for idx in targets}
    steps = max(1, int(round(max(0.2, duration) / DT)))
    for s in range(steps):
        if poc._interrupted(stop_event, queue):
            return True
        t = (s + 1) / steps
        a = t * t * (3 - 2 * t)  # smoothstep: gentle start and stop
        for idx, goal in targets.items():
            p.setJointMotorControl2(
                robot, idx, p.POSITION_CONTROL, targetPosition=start[idx] + (goal - start[idx]) * a, force=500
            )
        time.sleep(DT)
    return False


def set_joints(robot: int, joints: List[Dict], params: Dict, stop_event, queue) -> bool:
    by_name = {j["name"]: j for j in joints}
    targets: Dict[int, float] = {}
    relative = bool(params.get("relative", False))
    for name, deg in (params.get("joints") or {}).items():
        j = by_name.get(name)
        if j is None or j["type"] == "fixed":
            continue
        cur = p.getJointState(robot, j["index"])[0]
        amount = float(deg) if j["type"] == "prismatic" else math.radians(float(deg))  # prismatic = metres
        goal = (cur if relative else 0.0) + amount
        lo, hi = _limits(j)
        targets[j["index"]] = max(lo, min(hi, goal))
    if not targets:
        return False
    return _interpolate(robot, targets, float(params.get("duration", 1.5)), stop_event, queue)


def move_ee(robot: int, joints: List[Dict], params: Dict, stop_event, queue) -> bool:
    mv = movable(joints)
    pos = params.get("position")
    if not mv or not pos or len(pos) < 3:
        return False
    limits = [_limits(j) for j in mv]
    cur = [p.getJointState(robot, j["index"])[0] for j in mv]
    sol = p.calculateInverseKinematics(
        robot, mv[-1]["index"], [float(pos[0]), float(pos[1]), float(pos[2])],
        lowerLimits=[l[0] for l in limits], upperLimits=[l[1] for l in limits],
        jointRanges=[l[1] - l[0] for l in limits], restPoses=cur,
        maxNumIterations=300, residualThreshold=1e-4,
    )
    targets = {j["index"]: max(lo, min(hi, s)) for j, (lo, hi), s in zip(mv, limits, sol)}
    return _interpolate(robot, targets, float(params.get("duration", 2.0)), stop_event, queue)


def run(action: Dict, robot: int, joints: List[Dict], stop_event, queue) -> bool:
    prim, params = action.get("primitive"), action.get("params") or {}
    if prim == "set_joints":
        return set_joints(robot, joints, params, stop_event, queue)
    if prim == "move_ee":
        return move_ee(robot, joints, params, stop_event, queue)
    return False
