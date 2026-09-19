"""Parallel-jaw gripper support: `grasp` and `release` skills that work out the gripper's geometry themselves.

The AI should not have to guess finger lengths or which joint end means "open". We measure both from the URDF:
- which end of each finger joint opens the jaws (the one that increases finger separation),
- how far the fingertips reach ahead of the gripper's reference link, and how wide the jaws open.
`grasp` then opens the jaws, drives until the object sits between the fingers, and closes on it.
"""

import math
import re
from typing import Dict, List, Optional

import pybullet as p

import arm as arm_mod
import poc_ollama_pybullet as poc

NAME = re.compile(r"finger|gripper|claw|jaw|grip|pinch", re.I)


def _aabb_gap_y(a, b) -> float:
    return max(0.0, max(a[0][1], b[0][1]) - min(a[1][1], b[1][1]))


def find(robot: int, joints: List[Dict]) -> Optional[Dict]:
    """Detect sliding-finger grippers. Call while the robot is upright at yaw 0 (right after loading)."""
    fingers = [j for j in joints if j["type"] == "prismatic" and NAME.search(j["name"])]
    if not fingers:
        return None
    idx = [j["index"] for j in fingers]
    saved = {i: p.getJointState(robot, i)[0] for i in idx}

    def separation() -> float:
        pts = [p.getLinkState(robot, i, computeForwardKinematics=1)[4] for i in idx]
        return max((math.dist(a, b) for a in pts for b in pts), default=0.0)

    for j in fingers:
        p.resetJointState(robot, j["index"], j["lower_limit"])
    sep_lo = separation()
    for j in fingers:
        p.resetJointState(robot, j["index"], j["upper_limit"])
    sep_hi = separation()
    open_at_hi = sep_hi >= sep_lo
    open_vals = {j["name"]: (j["upper_limit"] if open_at_hi else j["lower_limit"]) for j in fingers}
    closed_vals = {j["name"]: (j["lower_limit"] if open_at_hi else j["upper_limit"]) for j in fingers}

    # Geometry with the jaws wide open.
    for j in fingers:
        p.resetJointState(robot, j["index"], open_vals[j["name"]])
    boxes = [p.getAABB(robot, i) for i in idx]
    ref_link = p.getJointInfo(robot, idx[0])[16]  # parent link of the first finger (the gripper base)
    ref_pos = p.getLinkState(robot, ref_link, computeForwardKinematics=1)[4] if ref_link >= 0 else p.getBasePositionAndOrientation(robot)[0]
    tip_ahead = max(b[1][0] for b in boxes) - ref_pos[0]
    opening = max((_aabb_gap_y(a, b) for a in boxes for b in boxes if a is not b), default=0.0)
    for i, v in saved.items():
        p.resetJointState(robot, i, v)

    return {
        "joints": [j["name"] for j in fingers],
        "open": open_vals,
        "closed": closed_vals,
        "ref_link": ref_link,
        "tip_ahead": round(max(0.1, tip_ahead), 3),
        "opening": round(opening, 3),
    }


def _move(robot: int, joints: List[Dict], values: Dict[str, float], duration: float, stop_event, queue) -> bool:
    by_name = {j["name"]: j["index"] for j in joints}
    targets = {by_name[n]: v for n, v in values.items() if n in by_name}
    return arm_mod._interpolate(robot, targets, duration, stop_event, queue)


def run(action: Dict, robot: int, joints: List[Dict], vehicle, gripper: Dict, stop_event, queue) -> bool:
    prim, params = action.get("primitive"), action.get("params") or {}
    if prim == "release":
        return _move(robot, joints, gripper["open"], 1.2, stop_event, queue)
    if prim != "grasp":
        return False
    if _move(robot, joints, gripper["open"], 1.2, stop_event, queue):
        return True
    if vehicle is not None and params.get("x") is not None:
        # Drive until the object's centre is between the fingers (about 55% of the way to the fingertips).
        nav = {
            "x": params["x"], "y": params["y"], "target_radius": params.get("target_radius", 0.5),
            "speed": 0.4, "duration": 60.0,
            "grasp_ref_link": gripper["ref_link"], "grasp_forward": gripper["tip_ahead"] * 0.55,
        }
        if vehicle._navigate((float(params["x"]), float(params["y"])), nav, stop_event, queue):
            return True
        vehicle.stop()
    return _move(robot, joints, gripper["closed"], 1.8, stop_event, queue)
