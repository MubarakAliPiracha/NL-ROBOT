"""
PoC: PyBullet + Ollama local LLM planner

Usage:
  python poc_ollama_pybullet.py [--urdf PATH]

Requirements:
  pip install pybullet requests

This script loads a URDF into a PyBullet GUI, lists controllable joints,
prompts a locally-running Ollama model to produce a strict JSON plan, and
executes the plan by moving joints in the GUI.

Notes:
- Configure the Ollama model by changing MODEL_NAME constant below.
- Ollama should be running locally (default: http://localhost:11434).

"""

import argparse
import json
import math
import time
import threading
from collections import deque
import re
import sys
from typing import List, Dict, Optional, Callable

import pybullet as p
import pybullet_data
import requests

# === Configuration ===
MODEL_NAME = "llama3.1"  # change if you run a different local Ollama model
OLLMAMA_BASE = "http://localhost:11434"
OLLAMA_API_GENERATE = OLLMAMA_BASE + "/api/generate"
# Temperature for consistent structured output
OLLAMA_TEMPERATURE = 0.15
# Duration to execute each motion (seconds)
EXEC_DURATION = 2.0
# Simulation timestep
TIMESTEP = 1.0 / 240.0

_DURATION_WORDS = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "half": 0.5,
}

_DURATION_TOKEN = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|half|\d+(?:\.\d+)?)"


# === PyBullet helpers (restored) ===


def load_robot(urdf_path: Optional[str] = None):
    print("Connecting to PyBullet (GUI)...")
    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)

    # plane
    plane_id = p.loadURDF("plane.urdf")

    if urdf_path:
        print(f"Loading URDF from: {urdf_path}")
        robot_id = p.loadURDF(urdf_path, useFixedBase=True)
    else:
        print("Loading default KUKA iiwa model from pybullet_data...")
        robot_id = p.loadURDF("kuka_iiwa/model.urdf", useFixedBase=True)

    print("Robot loaded. ID:", robot_id)
    return robot_id


def introspect_joints(robot_id: int) -> List[Dict]:
    num = p.getNumJoints(robot_id)
    print(f"Found {num} joints (including fixed). Inspecting...")
    joints = []
    for i in range(num):
        info = p.getJointInfo(robot_id, i)
        idx = info[0]
        name_b = info[1]
        jtype = info[2]
        lower = info[8]
        upper = info[9]
        name = name_b.decode("utf-8") if isinstance(name_b, bytes) else str(name_b)
        if jtype == p.JOINT_REVOLUTE:
            tstr = "revolute"
        elif jtype == p.JOINT_PRISMATIC:
            tstr = "prismatic"
        elif jtype == p.JOINT_CONTINUOUS:
            tstr = "continuous"
        elif jtype == p.JOINT_FIXED:
            tstr = "fixed"
        else:
            tstr = f"unknown({jtype})"

        joint = {
            "index": int(idx),
            "name": name,
            "type": tstr,
            "lower_limit": float(lower) if isinstance(lower, (int, float)) else None,
            "upper_limit": float(upper) if isinstance(upper, (int, float)) else None,
        }
        joints.append(joint)
    controllable = [j for j in joints if j["type"] != "fixed"]
    print(f"Controllable joints ({len(controllable)}): {[j['name'] for j in controllable]}")
    return joints


def find_end_effector_link_index(joints: List[Dict]) -> Optional[int]:
    """Heuristic: last non-fixed joint, preferring names that look like an EE."""
    controllable = [j for j in joints if j["type"] != "fixed"]
    if not controllable:
        return None
    for j in reversed(controllable):
        n = j["name"].lower()
        if any(k in n for k in ("ee", "gripper", "tool", "wrist", "hand", "end")):
            return int(j["index"])
    return int(controllable[-1]["index"])


def _physics_loop(stop_event: threading.Event):
    """Continuously step the physics simulation."""
    try:
        while not stop_event.is_set():
            p.stepSimulation()
            time.sleep(TIMESTEP)
    except Exception:
        pass


def _interrupted(stop_event: Optional[threading.Event], queue: Optional[deque]) -> bool:
    """True if shutdown was requested or a newer plan is waiting."""
    if stop_event is not None and stop_event.is_set():
        return True
    if queue is not None and len(queue) > 0:
        return True
    return False


def _sleep_for_duration(
    duration: float,
    stop_event: Optional[threading.Event] = None,
    queue: Optional[deque] = None,
    step_physics: bool = False,
) -> bool:
    """Sleep `duration` seconds, checking stop/queue every simulation step.

    Returns True if interrupted before the full duration elapsed.
    """
    endt = time.time() + max(0.0, float(duration))
    while time.time() < endt:
        if _interrupted(stop_event, queue):
            return True
        if step_physics:
            try:
                p.stepSimulation()
            except Exception:
                pass
        time.sleep(TIMESTEP)
    return False


def _for_duration_steps(
    duration: float,
    on_step: Callable[[float, int, int], None],
    stop_event: Optional[threading.Event] = None,
    queue: Optional[deque] = None,
    step_physics: bool = False,
) -> bool:
    """Call on_step(t, step_index, n_steps) each tick for `duration` seconds.

    Returns True if interrupted.
    """
    steps = max(1, int(round(float(duration) / TIMESTEP)))
    for s in range(steps):
        if _interrupted(stop_event, queue):
            return True
        on_step(s * TIMESTEP, s, steps)
        if step_physics:
            try:
                p.stepSimulation()
            except Exception:
                pass
        time.sleep(TIMESTEP)
    return False


def _wheel_joints(joints: List[Dict], capabilities: Optional[Dict]) -> List[Dict]:
    capabilities = capabilities or {}
    wheel_names = capabilities.get("wheels") or []
    if wheel_names:
        wheels = [j for j in joints if j["name"] in wheel_names]
        if wheels:
            return wheels
    return [j for j in joints if "wheel" in j["name"].lower() or j["type"] == "continuous"]


def _joint_index_by_name(joints: List[Dict], name: str) -> Optional[int]:
    for j in joints:
        if j["name"] == name:
            return j["index"]
    return None


def execute_action(
    robot_id: int,
    joints: List[Dict],
    action: Dict,
    capabilities: Optional[Dict] = None,
    stop_event: Optional[threading.Event] = None,
    queue: Optional[deque] = None,
    step_physics: bool = False,
) -> bool:
    """Execute a single primitive, conditional, or joint-delta ONCE.

    Repeat is never handled here — the caller loops the whole plan.
    Returns True if interrupted by stop_event or a newly queued plan.
    """
    if not isinstance(action, dict):
        return False

    if "condition" in action:
        return _execute_conditional(
            robot_id, joints, action, capabilities, stop_event, queue, step_physics
        )

    if "primitive" in action:
        return _execute_primitive(
            robot_id, joints, action, capabilities, stop_event, queue, step_physics
        )

    return _execute_joint_delta(robot_id, joints, action, stop_event, queue, step_physics)


def _execute_conditional(
    robot_id: int,
    joints: List[Dict],
    action: Dict,
    capabilities: Optional[Dict],
    stop_event: Optional[threading.Event],
    queue: Optional[deque],
    step_physics: bool,
) -> bool:
    cond = action.get("condition") or {}
    loop = bool(action.get("loop", False) or action.get("repeat", False))
    while not _interrupted(stop_event, queue):
        res = evaluate_condition(robot_id, joints, cond)
        branch = action.get("then") if res else action.get("else")
        if branch:
            try:
                if execute_plan(
                    robot_id,
                    joints,
                    branch,
                    capabilities=capabilities,
                    stop_event=stop_event,
                    queue=queue,
                    step_physics=step_physics,
                    repeat=False,
                    announce=False,
                ):
                    return True
            except Exception as e:
                print("Conditional branch execution error:", e)
        if not loop:
            break
        time.sleep(0.01)
    return _interrupted(stop_event, queue)


def _execute_primitive(
    robot_id: int,
    joints: List[Dict],
    action: Dict,
    capabilities: Optional[Dict],
    stop_event: Optional[threading.Event],
    queue: Optional[deque],
    step_physics: bool,
) -> bool:
    prim = action.get("primitive")
    params = action.get("params") or {}
    print(f"Executing primitive: {prim} params={params}")

    if prim in ("_noop", "noop"):
        return False

    if prim == "wait":
        duration = float(params.get("duration", 1.0))
        return _sleep_for_duration(duration, stop_event, queue, step_physics)

    if prim == "drive":
        wheels = _wheel_joints(joints, capabilities)
        if not wheels:
            print(" - No wheel joints detected, cannot drive.")
            return False
        indices = [w["index"] for w in wheels]
        speed = float(params.get("speed", 5.0))
        duration = float(params.get("duration", 2.0))
        for idx in indices:
            p.setJointMotorControl2(
                robot_id, idx, controlMode=p.VELOCITY_CONTROL, targetVelocity=speed, force=1000
            )
        interrupted = _sleep_for_duration(duration, stop_event, queue, step_physics)
        for idx in indices:
            p.setJointMotorControl2(
                robot_id, idx, controlMode=p.VELOCITY_CONTROL, targetVelocity=0, force=1000
            )
        return interrupted

    if prim == "turn":
        wheels = _wheel_joints(joints, capabilities)
        if not wheels or len(wheels) < 2:
            print(" - Not enough wheel joints for turning.")
            return False
        indices = [w["index"] for w in wheels]
        angle = float(params.get("angle_degrees", 45.0))
        duration = float(params.get("duration", 1.5))
        mid = len(indices) // 2
        left = indices[:mid]
        right = indices[mid:]
        vel = float(params.get("speed", 3.0))
        sign = 1.0 if angle > 0 else -1.0
        for i in left:
            p.setJointMotorControl2(
                robot_id, i, controlMode=p.VELOCITY_CONTROL, targetVelocity=vel * sign, force=1000
            )
        for i in right:
            p.setJointMotorControl2(
                robot_id, i, controlMode=p.VELOCITY_CONTROL, targetVelocity=-vel * sign, force=1000
            )
        interrupted = _sleep_for_duration(duration, stop_event, queue, step_physics)
        for i in indices:
            p.setJointMotorControl2(
                robot_id, i, controlMode=p.VELOCITY_CONTROL, targetVelocity=0, force=1000
            )
        return interrupted

    if prim == "flap":
        joint_names = params.get("joint_names") or []
        amp = float(params.get("amplitude_degrees", 20.0))
        freq = float(params.get("freq", 2.0))
        duration = float(params.get("duration", 3.0))
        indices = [
            _joint_index_by_name(joints, n)
            for n in joint_names
            if _joint_index_by_name(joints, n) is not None
        ]
        base_positions = {}
        for idx in indices:
            state = p.getJointState(robot_id, idx)
            base_positions[idx] = state[0]

        def on_flap(t, _s, _n):
            for idx in indices:
                target = base_positions[idx] + math.radians(amp) * math.sin(2 * math.pi * freq * t)
                p.setJointMotorControl2(
                    robot_id, idx, controlMode=p.POSITION_CONTROL, targetPosition=target, force=500
                )

        return _for_duration_steps(duration, on_flap, stop_event, queue, step_physics)

    if prim == "circle":
        joint_names = params.get("joint_names") or []
        if len(joint_names) < 2:
            print(" - Circle needs two joint names; skipping.")
            return False
        amp = float(params.get("amplitude_degrees", 10.0))
        freq = float(params.get("freq", 1.0))
        duration = float(params.get("duration", 4.0))
        idx_a = _joint_index_by_name(joints, joint_names[0])
        idx_b = _joint_index_by_name(joints, joint_names[1])
        if idx_a is None or idx_b is None:
            print(" - Circle joint names not found.")
            return False
        base_a = p.getJointState(robot_id, idx_a)[0]
        base_b = p.getJointState(robot_id, idx_b)[0]

        def on_circle(t, _s, _n):
            ta = base_a + math.radians(amp) * math.cos(2 * math.pi * freq * t)
            tb = base_b + math.radians(amp) * math.sin(2 * math.pi * freq * t)
            p.setJointMotorControl2(
                robot_id, idx_a, controlMode=p.POSITION_CONTROL, targetPosition=ta, force=500
            )
            p.setJointMotorControl2(
                robot_id, idx_b, controlMode=p.POSITION_CONTROL, targetPosition=tb, force=500
            )

        return _for_duration_steps(duration, on_circle, stop_event, queue, step_physics)

    if prim == "walk":
        leg_j = [
            j
            for j in joints
            if any(k in j["name"].lower() for k in ("hip", "knee", "ankle", "leg"))
        ]
        if not leg_j:
            print(" - No leg-like joints detected; walk not supported for this URDF.")
            return False
        indices = [j["index"] for j in leg_j]
        amp = math.radians(15)
        freq = 1.0
        duration = float(params.get("duration", 4.0))

        def on_walk(t, _s, _n):
            for i, idx in enumerate(indices):
                phase = (i % 2) * math.pi
                target = amp * math.sin(2 * math.pi * freq * t + phase)
                p.setJointMotorControl2(
                    robot_id, idx, controlMode=p.POSITION_CONTROL, targetPosition=target, force=500
                )

        return _for_duration_steps(duration, on_walk, stop_event, queue, step_physics)

    if prim in ("move_ee", "move_end_effector"):
        pos = params.get("position")
        duration = float(params.get("duration", 2.0))
        if not pos or len(pos) < 3:
            print(" - move_ee requires a 'position' param [x,y,z].")
            return False
        ee_index = find_end_effector_link_index(joints)
        if ee_index is None:
            print(" - No end-effector link found for IK.")
            return False
        target_pos = [float(pos[0]), float(pos[1]), float(pos[2])]
        try:
            ik_sol = p.calculateInverseKinematics(robot_id, ee_index, target_pos)
            numj = p.getNumJoints(robot_id)
            targets = {}
            for j in range(min(len(ik_sol), numj)):
                targets[j] = ik_sol[j]

            def on_move_ee(_t, s, steps):
                alpha = (s + 1) / steps
                for jidx, tgt in targets.items():
                    info = next((jj for jj in joints if jj["index"] == jidx), None)
                    if info is None or info["type"] == "fixed":
                        continue
                    current = p.getJointState(robot_id, jidx)[0]
                    pos_t = current + (tgt - current) * alpha
                    p.setJointMotorControl2(
                        robot_id, jidx, controlMode=p.POSITION_CONTROL, targetPosition=pos_t, force=500
                    )

            return _for_duration_steps(duration, on_move_ee, stop_event, queue, step_physics)
        except Exception as e:
            print(" - IK failed:", e)
            return False

    if prim == "avoid_obstacles":
        fwd_speed = float(params.get("speed", 3.0))
        rev_time = float(params.get("reverse_time", 0.6))
        turn_time = float(params.get("turn_time", 0.6))
        threshold = float(params.get("threshold", 0.5))
        wheels = _wheel_joints(joints, capabilities)
        if not wheels:
            print(" - avoid_obstacles: no wheel joints detected; skipping")
            return False
        indices = [w["index"] for w in wheels]
        while not _interrupted(stop_event, queue):
            dist = detect_obstacle_ahead(robot_id, distance=threshold)
            if dist is not None and dist <= threshold:
                for idx in indices:
                    p.setJointMotorControl2(
                        robot_id, idx, controlMode=p.VELOCITY_CONTROL, targetVelocity=-fwd_speed, force=1000
                    )
                if _sleep_for_duration(rev_time, stop_event, queue, step_physics):
                    break
                mid = len(indices) // 2
                left = indices[:mid]
                right = indices[mid:]
                for i in left:
                    p.setJointMotorControl2(
                        robot_id, i, controlMode=p.VELOCITY_CONTROL, targetVelocity=fwd_speed, force=1000
                    )
                for i in right:
                    p.setJointMotorControl2(
                        robot_id, i, controlMode=p.VELOCITY_CONTROL, targetVelocity=-fwd_speed, force=1000
                    )
                if _sleep_for_duration(turn_time, stop_event, queue, step_physics):
                    break
            else:
                for idx in indices:
                    p.setJointMotorControl2(
                        robot_id, idx, controlMode=p.VELOCITY_CONTROL, targetVelocity=fwd_speed, force=1000
                    )
                if _sleep_for_duration(0.05, stop_event, queue, step_physics):
                    break
        for idx in indices:
            p.setJointMotorControl2(
                robot_id, idx, controlMode=p.VELOCITY_CONTROL, targetVelocity=0, force=1000
            )
        return _interrupted(stop_event, queue)

    print(f" - Unknown primitive: {prim}")
    return False


def _execute_joint_delta(
    robot_id: int,
    joints: List[Dict],
    action: Dict,
    stop_event: Optional[threading.Event],
    queue: Optional[deque],
    step_physics: bool,
) -> bool:
    name_to_joint = {j["name"]: j for j in joints}
    jname = action.get("joint_name")
    delta_deg = action.get("target_change_degrees")
    print(f"Executing joint action: joint={jname}, delta_deg={delta_deg}")
    if jname not in name_to_joint:
        print(f" - Skipping: joint name '{jname}' not found in robot joints.")
        return False
    jinfo = name_to_joint[jname]
    jindex = jinfo["index"]
    jtype = jinfo["type"]
    lower = jinfo.get("lower_limit")
    upper = jinfo.get("upper_limit")
    state = p.getJointState(robot_id, jindex)
    current_pos = state[0] if state is not None else 0.0
    delta_rad = math.radians(float(delta_deg))
    target = current_pos + delta_rad
    if jtype != "continuous" and lower is not None and upper is not None and lower < upper:
        clamped = max(min(target, upper), lower)
        if clamped != target:
            print(f" - Clamped target from {target:.3f} to {clamped:.3f} due to limits [{lower}, {upper}].")
        target = clamped
    p.setJointMotorControl2(
        bodyUniqueId=robot_id,
        jointIndex=jindex,
        controlMode=p.POSITION_CONTROL,
        targetPosition=target,
        force=500,
    )
    return _sleep_for_duration(EXEC_DURATION, stop_event, queue, step_physics)


def execute_plan(
    robot_id: int,
    joints: List[Dict],
    plan: List[Dict],
    capabilities: Optional[Dict] = None,
    stop_event: Optional[threading.Event] = None,
    queue: Optional[deque] = None,
    step_physics: bool = False,
    repeat: bool = False,
    announce: bool = False,
) -> bool:
    """Run a plan in order. If repeat=True, loop the whole sequence until interrupted.

    Returns True if interrupted by stop_event or a newly queued plan.
    """
    if announce:
        print("=== Interpreted plan (about to execute) ===")
        print(json.dumps({"sequence": plan, "repeat": bool(repeat)}, indent=2, default=str))

    caps = capabilities if capabilities is not None else analyze_capabilities(robot_id, joints)
    was_interrupted = False

    while True:
        if _interrupted(stop_event, queue):
            was_interrupted = True
            break
        stop_all = False
        for action in plan:
            if _interrupted(stop_event, queue):
                was_interrupted = True
                stop_all = True
                break
            if execute_action(
                robot_id,
                joints,
                action,
                capabilities=caps,
                stop_event=stop_event,
                queue=queue,
                step_physics=step_physics,
            ):
                was_interrupted = True
                stop_all = True
                break
        if stop_all:
            break
        if not repeat:
            break

    if announce:
        if was_interrupted:
            print("Plan interrupted (new command or quit).")
        else:
            print("Plan execution finished.")
    return was_interrupted


def _worker_loop(robot_id: int, joints: List[Dict], queue: deque, stop_event: threading.Event):
    """Consume queued plans and execute them via the shared executor."""
    capabilities = analyze_capabilities(robot_id, joints)

    while not stop_event.is_set():
        try:
            if len(queue) == 0:
                time.sleep(0.01)
                continue
            item = queue.popleft()
            if item is None:
                continue

            if isinstance(item, dict) and "plan" in item:
                plan_items = item.get("plan") or []
                plan_repeat = bool(item.get("repeat", False))
            elif isinstance(item, list):
                plan_items = item
                plan_repeat = False
            else:
                plan_items = [item]
                plan_repeat = False

            if not plan_items:
                continue

            is_one_shot = any(
                isinstance(a, dict) and (a.get("params") or {}).get("one_shot", False)
                for a in plan_items
            )

            execute_plan(
                robot_id,
                joints,
                plan_items,
                capabilities=capabilities,
                stop_event=stop_event,
                queue=queue,
                step_physics=False,
                repeat=plan_repeat and not is_one_shot,
                announce=True,
            )
        except Exception as e:
            if stop_event.is_set():
                break
            print("Worker loop error:", e)
            time.sleep(0.1)


def build_planner_prompt(joint_list: List[Dict], user_command: str) -> str:
    joints_short = [
        {
            "name": j["name"],
            "type": j["type"],
            "lower_limit": j.get("lower_limit"),
            "upper_limit": j.get("upper_limit"),
        }
        for j in joint_list
        if j["type"] != "fixed"
    ]

    capabilities = analyze_capabilities(None, joint_list)
    names = [j["name"] for j in joints_short]
    j1 = names[0] if names else "joint1"
    j2 = names[1] if len(names) > 1 else j1

    prompt = (
        "You are a planner that MUST return ONLY strict JSON with no explanations, no markdown, and no extra text.\n"
        "Return a single JSON object of this exact shape:\n"
        '{"plan": [ ...ordered primitives... ], "repeat": true_or_false}\n\n'
        "A plan is an ORDERED list. Primitives MUST execute one after another. "
        "Each primitive must fully finish (including its full duration) before the next starts.\n"
        '"repeat" is a TOP-LEVEL flag only. NEVER put "repeat" inside a primitive\'s params.\n'
        "If repeat is true, the ENTIRE plan list is looped from the start after the last primitive finishes. "
        "Do NOT loop a single primitive in place.\n\n"
        "Allowed primitives (use only these names):\n"
        ' - wait: {"primitive":"wait","params":{"duration":1.0}}\n'
        ' - drive: {"primitive":"drive","params":{"speed":5.0,"duration":2.0}}\n'
        ' - turn: {"primitive":"turn","params":{"angle_degrees":30.0,"duration":1.5}}\n'
        ' - flap: {"primitive":"flap","params":{"joint_names":["'
        + j1
        + '"],"amplitude_degrees":20,"freq":2.0,"duration":3.0}}\n'
        ' - circle: {"primitive":"circle","params":{"joint_names":["'
        + j1
        + '","'
        + j2
        + '"],"amplitude_degrees":10,"freq":1.0,"duration":4.0}}\n'
        ' - walk: {"primitive":"walk","params":{"speed":0.5,"duration":4.0}}\n'
        ' - move_ee: {"primitive":"move_ee","params":{"position":[0.3,0.0,0.5],"duration":2.0}}\n\n'
        "Capabilities (auto-detected):\n"
        + json.dumps(capabilities, indent=2)
        + "\n\n"
        "joints = "
        + json.dumps(joints_short, indent=2)
        + "\n\n"
        "=== FEW-SHOT EXAMPLES (copy this structure exactly) ===\n\n"
        'User: "drive forward for 3 seconds"\n'
        '{"plan":[{"primitive":"drive","params":{"speed":5.0,"duration":3.0}}],"repeat":false}\n\n'
        'User: "turn left 45 degrees"\n'
        '{"plan":[{"primitive":"turn","params":{"angle_degrees":45.0,"duration":1.5}}],"repeat":false}\n\n'
        'User: "flap the arms"\n'
        '{"plan":[{"primitive":"flap","params":{"joint_names":["'
        + j1
        + '"],"amplitude_degrees":25,"freq":2.0,"duration":3.0}}],"repeat":false}\n\n'
        'User: "move in a circle for 4 seconds"\n'
        '{"plan":[{"primitive":"circle","params":{"joint_names":["'
        + j1
        + '","'
        + j2
        + '"],"amplitude_degrees":15,"freq":1.0,"duration":4.0}}],"repeat":false}\n\n'
        'User: "walk for 4 seconds"\n'
        '{"plan":[{"primitive":"walk","params":{"speed":0.5,"duration":4.0}}],"repeat":false}\n\n'
        'User: "move the end effector to 0.3 0.0 0.5"\n'
        '{"plan":[{"primitive":"move_ee","params":{"position":[0.3,0.0,0.5],"duration":2.0}}],"repeat":false}\n\n'
        'User: "wait 1 second" / "pause for 1 second" / "stop for a second"\n'
        '{"plan":[{"primitive":"wait","params":{"duration":1.0}}],"repeat":false}\n\n'
        "=== COMPOUND / SEQUENCED COMMANDS (repeat applies to the WHOLE list) ===\n\n"
        'User: "circle for 2 seconds, then stop for 1 second, then repeat"\n'
        '{"plan":['
        '{"primitive":"circle","params":{"joint_names":["'
        + j1
        + '","'
        + j2
        + '"],"amplitude_degrees":15,"freq":1.0,"duration":2.0}},'
        '{"primitive":"wait","params":{"duration":1.0}}'
        '],"repeat":true}\n\n'
        'User: "drive for 2 seconds, wait 1 second"\n'
        '{"plan":['
        '{"primitive":"drive","params":{"speed":5.0,"duration":2.0}},'
        '{"primitive":"wait","params":{"duration":1.0}}'
        '],"repeat":false}\n\n'
        'User: "move in a circle for two seconds, stop for a second, do it again, then repeat the process"\n'
        '{"plan":['
        '{"primitive":"circle","params":{"joint_names":["'
        + j1
        + '","'
        + j2
        + '"],"amplitude_degrees":15,"freq":1.0,"duration":2.0}},'
        '{"primitive":"wait","params":{"duration":1.0}}'
        '],"repeat":true}\n\n'
        "You may also return a conditional object inside the plan array:\n"
        '{"condition":{"type":"obstacle_ahead","threshold":0.5},'
        '"then":[{"primitive":"turn","params":{"angle_degrees":45,"duration":1.5}}],'
        '"else":[{"primitive":"drive","params":{"duration":1.0}}],'
        '"loop":true}\n\n'
        'User command: "' + user_command + '"\n\n'
        "Return ONLY the JSON object {\"plan\":[...],\"repeat\":bool}. No markdown. No extra keys. No extra text."
    )
    return prompt


def get_robot_state(robot_id: int, joints: List[Dict]) -> Dict:
    """Return a small snapshot of robot state: joint positions and a likely end-effector pose."""
    state = {}
    try:
        positions = {}
        for j in joints:
            if j["type"] == "fixed":
                continue
            idx = j["index"]
            js = p.getJointState(robot_id, idx)
            positions[j["name"]] = float(js[0]) if js is not None else 0.0
        ee_index = find_end_effector_link_index(joints)
        if ee_index is not None:
            try:
                link_state = p.getLinkState(robot_id, ee_index)
                pose = list(link_state[4]) if link_state and len(link_state) > 4 else None
            except Exception:
                pose = None
        else:
            pose = None
        state["joints"] = positions
        state["end_effector_pose"] = pose
    except Exception:
        state = {"joints": {}, "end_effector_pose": None}
    return state


def evaluate_condition(robot_id: int, joints: List[Dict], cond: Dict) -> bool:
    """Evaluate a simple condition dict against current robot state.

    Supported condition types:
    - obstacle_ahead: {"type":"obstacle_ahead", "threshold": 0.5}
    - joint_position: {"type":"joint_position", "joint_name": "joint1", "op": "<", "value": 0.3}
    - ee_distance: {"type":"ee_distance", "point": [x,y,z], "op": "<", "value": 0.5}
    """
    try:
        t = cond.get("type")
        if t == "obstacle_ahead":
            thr = float(cond.get("threshold", 0.5))
            d = detect_obstacle_ahead(robot_id, distance=max(1.0, thr * 2.0))
            return d is not None and d <= thr
        if t == "joint_position":
            jn = cond.get("joint_name")
            op = cond.get("op", "<")
            val = float(cond.get("value", 0.0))
            js = next((j for j in joints if j["name"] == jn), None)
            if js is None:
                return False
            st = p.getJointState(robot_id, js["index"])
            pos = float(st[0]) if st is not None else 0.0
            if op == "<":
                return pos < val
            if op == ">":
                return pos > val
            if op == "==":
                return abs(pos - val) < 1e-3
            return False
        if t == "ee_distance":
            pt = cond.get("point") or [0, 0, 0]
            op = cond.get("op", "<")
            val = float(cond.get("value", 0.5))
            ee = find_end_effector_link_index(joints)
            if ee is None:
                return False
            ls = p.getLinkState(robot_id, ee)
            if not ls:
                return False
            pos = ls[4]
            dist = math.sqrt((pos[0] - pt[0]) ** 2 + (pos[1] - pt[1]) ** 2 + (pos[2] - pt[2]) ** 2)
            if op == "<":
                return dist < val
            if op == ">":
                return dist > val
            return False
    except Exception:
        return False
    return False


def detect_obstacle_ahead(robot_id: int, distance: float = 0.6, height: float = 0.2) -> Optional[float]:
    """Raycast forward from the robot base to detect obstacles. Returns hit distance or None."""
    try:
        base = p.getBasePositionAndOrientation(robot_id)
        if not base:
            return None
        pos, orn = base
        # forward vector from orientation
        mat = p.getMatrixFromQuaternion(orn)
        fx = mat[0]
        fy = mat[3]
        fz = mat[6]
        from_pos = [pos[0], pos[1], pos[2] + height]
        to_pos = [pos[0] + fx * distance, pos[1] + fy * distance, pos[2] + height]
        ray = p.rayTest(from_pos, to_pos)
        if not ray or len(ray) == 0:
            return None
        hit = ray[0]
        hit_fraction = hit[2]
        if hit_fraction < 1.0:
            return hit_fraction * distance
        return None
    except Exception:
        return None


def analyze_capabilities(robot_id: Optional[int], joints: List[Dict]) -> Dict:
    """Analyze joint list and return a small capabilities summary for the prompt."""
    wheels = []
    arms = []
    legs = []
    continuous = []
    revolute = []
    for j in joints:
        name = j["name"]
        jt = j["type"]
        lname = name.lower()
        if jt == "continuous":
            continuous.append(name)
        if jt in ("revolute", "continuous"):
            revolute.append(name)
        if "wheel" in lname or "tire" in lname:
            wheels.append(name)
        if any(k in lname for k in ("shoulder", "elbow", "wrist", "arm")):
            arms.append(name)
        if any(k in lname for k in ("hip", "knee", "ankle", "leg")):
            legs.append(name)

    # If we have a robot_id, try to detect wheels by link world Z position (close to ground)
    if robot_id is not None:
        try:
            wheel_candidates = []
            for j in joints:
                if j["type"] not in ("revolute", "continuous"):
                    continue
                idx = j["index"]
                lname_j = j["name"].lower()
                try:
                    ls = p.getLinkState(robot_id, idx)
                    if ls and len(ls) > 4 and ls[4] is not None:
                        wz = ls[4][2]
                    else:
                        wz = None
                except Exception:
                    wz = None
                if (wz is not None and wz < 0.2) or ("wheel" in lname_j or "tire" in lname_j):
                    wheel_candidates.append(j["name"])
            if wheel_candidates:
                wheels = wheel_candidates
        except Exception:
            pass

    return {
        "wheels": wheels,
        "arms": arms,
        "legs": legs,
        "continuous": continuous,
        "revolute": revolute,
        "controllable_count": len([j for j in joints if j["type"] != "fixed"]),
    }


def extract_json_payload(text: str):
    """Extract the first JSON array or object from model text (markdown-tolerant)."""
    if not text:
        return None
    stripped = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "")
    decoder = json.JSONDecoder()
    for i, ch in enumerate(stripped):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(stripped[i:])
                return obj
            except json.JSONDecodeError:
                continue
    return None


def extract_first_json_array(text: str) -> Optional[str]:
    """Compatibility helper: return the first JSON array substring if present."""
    obj = extract_json_payload(text)
    if isinstance(obj, list):
        return json.dumps(obj)
    if isinstance(obj, dict) and isinstance(obj.get("plan"), list):
        return json.dumps(obj["plan"])
    return None


def _normalize_planner_output(obj) -> Optional[Dict]:
    """Normalize LLM/local output to {plan: [...], repeat: bool}. Empty -> None."""
    if obj is None:
        return None
    plan = None
    repeat = False
    if isinstance(obj, list):
        if not obj:
            return None
        plan = obj
    elif isinstance(obj, dict):
        if isinstance(obj.get("plan"), list):
            if not obj["plan"]:
                return None
            plan = obj["plan"]
            repeat = bool(obj.get("repeat", False))
        elif "primitive" in obj:
            plan = [obj]
            repeat = bool(obj.get("repeat", False))
        else:
            return None
    else:
        return None

    # Promote any leftover per-primitive repeat onto the plan, then strip it.
    cleaned = []
    for a in plan:
        if isinstance(a, dict):
            item = dict(a)
            params = item.get("params")
            if isinstance(params, dict):
                params = dict(params)
                if params.pop("repeat", False):
                    repeat = True
                item["params"] = params
            cleaned.append(item)
        else:
            cleaned.append(a)
    return {"plan": cleaned, "repeat": repeat}


def call_ollama_planner(robot_id: int, joint_list: List[Dict], user_command: str) -> Optional[Dict]:
    prompt = build_planner_prompt(joint_list, user_command)
    try:
        state = get_robot_state(robot_id, joint_list)
        prompt += "\n\nCurrent state: " + json.dumps(state, indent=2)
    except Exception:
        pass
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "temperature": OLLAMA_TEMPERATURE,
        "max_tokens": 512,
        "stream": False,
    }
    print("Sending prompt to Ollama (local) with low temperature...")
    try:
        resp = requests.post(OLLAMA_API_GENERATE, json=payload, timeout=15)
    except requests.RequestException as e:
        print("Error contacting Ollama API:", e)
        return None

    if resp.status_code != 200:
        print(f"Ollama returned status {resp.status_code}: {resp.text}")
        return None

    try:
        rj = resp.json()
    except Exception:
        print("Ollama response not JSON. Raw response:\n", resp.text)
        return None

    candidate_text = None
    if isinstance(rj, dict) and "results" in rj:
        results = rj.get("results")
        if isinstance(results, list) and len(results) > 0:
            parts = []
            for chunk in results:
                if isinstance(chunk, dict):
                    c = chunk.get("content") or chunk.get("output") or chunk.get("text")
                    if isinstance(c, list):
                        for el in c:
                            if isinstance(el, dict) and el.get("type") == "output_text":
                                parts.append(el.get("text", ""))
                            elif isinstance(el, str):
                                parts.append(el)
                    elif isinstance(c, str):
                        parts.append(c)
            candidate_text = "\n".join(parts).strip()
    if not candidate_text:
        if isinstance(rj, dict) and "text" in rj and isinstance(rj["text"], str):
            candidate_text = rj["text"]
        elif isinstance(rj, dict) and "response" in rj and isinstance(rj["response"], str):
            candidate_text = rj["response"]

    if not candidate_text:
        candidate_text = resp.text

    print("Raw model response:\n", candidate_text)

    obj = extract_json_payload(candidate_text)
    if obj is None:
        print(
            "Could not parse a valid JSON plan from the model response.\n"
            "Raw response (above) — falling back to the local parser."
        )
        return None

    normalized = _normalize_planner_output(obj)
    if normalized is None:
        print("Parsed JSON is empty or not a plan. Raw parsed object:", obj)
        return None
    return normalized


def _parse_duration_token(token: str) -> Optional[float]:
    t = str(token).strip().lower()
    if t in _DURATION_WORDS:
        return float(_DURATION_WORDS[t])
    try:
        return float(t)
    except ValueError:
        return None


def _extract_duration(text: str, default: float) -> float:
    m = re.search(
        r"(?:for|of)\s+(" + _DURATION_TOKEN + r")\s*(?:seconds?|s)\b",
        text,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"\b(" + _DURATION_TOKEN + r")\s*(?:seconds?|s)\b",
            text,
            re.IGNORECASE,
        )
    if m:
        v = _parse_duration_token(m.group(1))
        if v is not None:
            return v
    return default


def _user_wants_repeat(text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"repeat(?:edly)?|repeatedly|continuously|forever|"
            r"until stopped|until interrupted|"
            r"keep (?:going|moving|doing)|"
            r"do (?:it|that) again|"
            r"once more|"
            r"over and over|"
            r"again and again|"
            r"repeat the process"
            r")\b",
            text,
            re.IGNORECASE,
        )
    )


def _nonfixed_names(joint_list: List[Dict], n: int = 2) -> List[str]:
    names = [j["name"] for j in joint_list if j["type"] != "fixed"]
    return names[:n]


def _flap_params(joint_list: List[Dict], duration: float) -> Dict:
    arm_j = [
        j["name"]
        for j in joint_list
        if any(k in j["name"].lower() for k in ("shoulder", "elbow", "wrist", "arm"))
    ]
    if not arm_j:
        arm_j = _nonfixed_names(joint_list, 2)
    return {"joint_names": arm_j, "amplitude_degrees": 25, "freq": 2.0, "duration": duration}


def _circle_params(joint_list: List[Dict], duration: float) -> Dict:
    pair = _nonfixed_names(joint_list, 2)
    return {"joint_names": pair, "amplitude_degrees": 15, "freq": 1.0, "duration": duration}


def _head_to_primitive(head: str, joint_list: List[Dict], duration: float, full_text: str) -> Optional[Dict]:
    h = head.lower()
    if "circle" in h:
        return {"primitive": "circle", "params": _circle_params(joint_list, duration)}
    if "drive" in h or "forward" in h:
        return {"primitive": "drive", "params": {"speed": 5.0, "duration": duration}}
    if h.startswith("turn") or h == "turn":
        angle = 45.0
        if re.search(r"\bright\b", h) or re.search(r"\bturn\s+right\b", full_text, re.IGNORECASE):
            angle = -45.0
        m_ang = re.search(r"(-?\d+(?:\.\d+)?)\s*degrees", full_text, re.IGNORECASE)
        if m_ang:
            angle = float(m_ang.group(1))
            if re.search(r"\bright\b", full_text, re.IGNORECASE):
                angle = -abs(angle)
            elif re.search(r"\bleft\b", full_text, re.IGNORECASE):
                angle = abs(angle)
        return {"primitive": "turn", "params": {"angle_degrees": angle, "duration": duration}}
    if "flap" in h:
        return {"primitive": "flap", "params": _flap_params(joint_list, duration)}
    if "walk" in h:
        return {"primitive": "walk", "params": {"speed": 0.5, "duration": duration}}
    if "wait" in h or "pause" in h:
        return {"primitive": "wait", "params": {"duration": duration}}
    return None


def parse_compound_sequence(joint_list: List[Dict], user_command: str) -> Optional[Dict]:
    """Deterministic parser for '<primitive> for X seconds, stop/wait/pause for Y seconds[, repeat]'.

    Returns {plan, repeat} or None if the utterance is not this compound pattern.
    """
    text = user_command.strip()
    compound_re = re.compile(
        r"(move\s+in\s+a\s+circle|go\s+in\s+a\s+circle|circle|"
        r"drive|go\s+forward|move\s+forward|"
        r"turn(?:\s+(?:left|right))?|flap|walk|wait|pause)"
        r".{0,80}?"
        r"(?:for|of)\s+(" + _DURATION_TOKEN + r")\s*(?:seconds?|s)\b"
        r".{0,80}?"
        r"(?:then\s+)?(?:stop|wait|pause|rest|halt)"
        r".{0,40}?"
        r"(?:for|of)?\s*(" + _DURATION_TOKEN + r")\s*(?:seconds?|s)\b",
        re.IGNORECASE | re.DOTALL,
    )
    m = compound_re.search(text)
    if not m:
        return None
    head = m.group(1)
    d1 = _parse_duration_token(m.group(2))
    d2 = _parse_duration_token(m.group(3))
    if d1 is None or d2 is None:
        return None
    first = _head_to_primitive(head, joint_list, d1, text)
    if first is None:
        return None
    plan = [first, {"primitive": "wait", "params": {"duration": d2}}]
    return {"plan": plan, "repeat": _user_wants_repeat(text)}


def local_simple_planner(joint_list: List[Dict], user_command: str) -> Optional[Dict]:
    """Regex fallback planner. Returns {plan: [...], repeat: bool} or None.

    Handles the compound pattern '<primitive> for X seconds, stop/wait/pause for Y, repeat'
    deterministically, plus single-primitive and joint-delta commands.
    """
    text = user_command

    compound = parse_compound_sequence(joint_list, text)
    if compound:
        return compound

    pattern = re.compile(
        r"(?:rotate|increase|decrease|lower|raise)?\s*([\w_]+)\s*(?:by|of)?\s*(-?\d+(?:\.\d+)?)\s*degrees",
        re.IGNORECASE,
    )
    matches = pattern.findall(text)
    if matches:
        plan = []
        for jname, deg_s in matches:
            try:
                deg = float(deg_s)
            except Exception:
                continue
            plan.append({"joint_name": jname, "target_change_degrees": deg})
        if plan:
            return {"plan": plan, "repeat": _user_wants_repeat(text)}
        return None

    repeat = _user_wants_repeat(text)

    if re.search(r"\bflap\b", text, re.IGNORECASE):
        duration = _extract_duration(text, 3.0)
        return {"plan": [{"primitive": "flap", "params": _flap_params(joint_list, duration)}], "repeat": repeat}

    if re.search(r"\bcircle\b", text, re.IGNORECASE):
        duration = _extract_duration(text, 4.0)
        return {"plan": [{"primitive": "circle", "params": _circle_params(joint_list, duration)}], "repeat": repeat}

    if re.search(r"\b(?:wait|pause|stop|rest|halt)\b", text, re.IGNORECASE) and re.search(
        r"second|\d+(?:\.\d+)?\s*s\b", text, re.IGNORECASE
    ):
        duration = _extract_duration(text, 1.0)
        return {"plan": [{"primitive": "wait", "params": {"duration": duration}}], "repeat": repeat}

    if re.search(r"\bdrive\b|\bgo forward\b|\bmove forward\b", text, re.IGNORECASE):
        duration = _extract_duration(text, 3.0)
        return {"plan": [{"primitive": "drive", "params": {"speed": 5.0, "duration": duration}}], "repeat": repeat}

    if re.search(r"\bavoid\b|\bobstacle\b|\bstop if\b", text, re.IGNORECASE):
        return {
            "plan": [
                {
                    "primitive": "avoid_obstacles",
                    "params": {"speed": 3.0, "reverse_time": 0.6, "turn_time": 0.6, "threshold": 0.5},
                }
            ],
            "repeat": False,
        }

    mturn = re.search(r"\bturn\s+(left|right)\b(?:\s+by\s+(-?\d+(?:\.\d+)?))?", text, re.IGNORECASE)
    if mturn:
        direction = mturn.group(1)
        angle = float(mturn.group(2)) if mturn.group(2) else 45.0
        if direction.lower() == "left":
            angle = abs(angle)
        else:
            angle = -abs(angle)
        duration = _extract_duration(text, 1.5)
        return {
            "plan": [{"primitive": "turn", "params": {"angle_degrees": angle, "duration": duration}}],
            "repeat": repeat,
        }

    if re.search(r"\bwalk\b", text, re.IGNORECASE):
        duration = _extract_duration(text, 4.0)
        return {"plan": [{"primitive": "walk", "params": {"speed": 0.5, "duration": duration}}], "repeat": repeat}

    mcoords = re.search(
        r"move(?:\s+\w+)?\s+to\s*([-+]?[0-9]*\.?[0-9]+)\s*,?\s*([-+]?[0-9]*\.?[0-9]+)\s*,?\s*([-+]?[0-9]*\.?[0-9]+)",
        text,
        re.IGNORECASE,
    )
    if mcoords:
        x = float(mcoords.group(1))
        y = float(mcoords.group(2))
        z = float(mcoords.group(3))
        duration = _extract_duration(text, 2.0)
        return {
            "plan": [{"primitive": "move_ee", "params": {"position": [x, y, z], "duration": duration}}],
            "repeat": repeat,
        }

    return None


# === REPL and main ===

def repl_loop(robot_id: int, joints: List[Dict]):
    print("Entering REPL. Type 'quit' to stop, Ctrl+C to exit the program.")
    queue = repl_loop._queue
    stop_event = repl_loop._stop_event
    while True:
        user = input("Enter a natural-language command for the robot: ").strip()
        if not user:
            continue
        if user.lower() in ("quit", "exit"):
            print("Interrupting the current plan and exiting REPL...")
            # A queued item makes in-progress primitives abort on the next sim step.
            queue.append({"plan": [], "repeat": False})
            break

        envelope = None
        # Compound sequenced commands are parsed deterministically so they work
        # even if the local LLM returns malformed JSON.
        compound = parse_compound_sequence(joints, user)
        if compound:
            print("Compound sequence matched by local parser (deterministic, skipping LLM).")
            envelope = compound
        else:
            envelope = call_ollama_planner(robot_id, joints, user)
            if envelope is None or not envelope.get("plan"):
                print("No valid plan returned from Ollama. Attempting local fallback parser...")
                envelope = local_simple_planner(joints, user)
                if envelope:
                    print("Local fallback parsed plan:", json.dumps(envelope, indent=2))
                else:
                    print("Local fallback could not parse a plan. Try a different phrasing or start Ollama.")
                    continue

        plan = envelope.get("plan") or []
        if not plan:
            print("Plan is empty; nothing to enqueue.")
            continue

        repeat_flag = bool(envelope.get("repeat")) or _user_wants_repeat(user)
        print("=== Interpreted plan (enqueued) ===")
        print(json.dumps({"sequence": plan, "repeat": repeat_flag}, indent=2))
        queue.append({"plan": plan, "repeat": repeat_flag})
        print(f"Enqueued plan (queue length now {len(queue)}). repeat={repeat_flag}")


def main():
    parser = argparse.ArgumentParser(description="PyBullet + Ollama PoC planner")
    parser.add_argument("--urdf", type=str, default=None, help="Path to URDF file to load (optional)")
    args = parser.parse_args()

    robot_id = load_robot(args.urdf)
    joints = introspect_joints(robot_id)
    queue = deque()
    stop_event = threading.Event()

    repl_loop._queue = queue
    repl_loop._stop_event = stop_event

    physics_thread = threading.Thread(target=_physics_loop, args=(stop_event,), daemon=True)
    worker_thread = threading.Thread(target=_worker_loop, args=(robot_id, joints, queue, stop_event), daemon=True)
    physics_thread.start()
    worker_thread.start()

    try:
        repl_loop(robot_id, joints)
    finally:
        stop_event.set()
        print("Waiting for background threads to exit...")
        physics_thread.join(timeout=1.0)
        worker_thread.join(timeout=1.0)
        try:
            p.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
