"""Sequential plan worker: turns normalized [{primitive, params}] into ROS motion.

One step at a time, blocking, on its own thread. Every inner loop checks `cancel` and a
wall-clock deadline, so /api/stop always lands promptly.

Why there is no Nav2 here: `go_to` and `avoid_obstacles` run as controllers on
ground-truth odometry. That is not a shortcut relative to the product being ported -- the
PyBullet original also drove off ground-truth poses and had no SLAM -- and Nav2's costmap
/ AMCL / behaviour-tree configuration is a day of work on its own.
"""

import math
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from ros_node import SimNode, wrap_pi

CONTROL_HZ = 20.0
CONTROL_DT = 1.0 / CONTROL_HZ

MAX_LINEAR = 0.6      # m/s
MAX_ANGULAR = 1.5     # rad/s
OBSTACLE_STOP = 0.45  # m, reactive brake distance for `safe`


class PlanExecutor:
    def __init__(self, node: SimNode, world_provider: Callable[[], List[Dict]], kin) -> None:
        self.node = node
        self.world = world_provider  # returns the current WorldObject list
        self.kin = kin               # Kinematics bound to the loaded URDF
        self.revolute = set(kin.arm_joints)
        self.queue: List[Dict] = []
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.active = False
        self._repeat_plan: Optional[List[Dict]] = None

        # Kinematic grasp state (see grasp() for why this is not a DetachableJoint).
        self.held_id: Optional[str] = None
        self._held_offset = (0.0, 0.0, 0.0)

        self._scan: Tuple[float, List[float]] = (8.0, [])

        threading.Thread(target=self._run, daemon=True, name="plan-executor").start()
        threading.Thread(target=self._servo_held, daemon=True, name="grasp-servo").start()

    # ---------- queue control ----------

    def submit(self, steps: List[Dict], repeat: bool = False) -> None:
        # Plans APPEND, matching the original: asking for a wave mid-drive queues it
        # rather than cancelling the drive.
        with self.lock:
            self.cancel.clear()
            self.queue.extend(steps)
            self._repeat_plan = list(steps) if repeat else None

    def stop(self) -> None:
        self.cancel.set()
        with self.lock:
            self.queue.clear()
            self._repeat_plan = None
        self.node.halt()
        self.node.cancel_trajectory()

    def status(self) -> Tuple[int, bool]:
        """(queued, active) read together so they can never disagree.

        `active` must already be true in the window between submit() and the worker
        picking the step up, otherwise the UI briefly shows an idle robot mid-command.
        """
        with self.lock:
            return len(self.queue), bool(self.active or self.queue)

    def set_scan(self, front: float, ranges: List[float]) -> None:
        self._scan = (front, ranges)  # one assignment: front and ranges stay same-tick

    @property
    def _scan_front(self) -> float:
        return self._scan[0]

    @property
    def _scan_ranges(self) -> List[float]:
        return self._scan[1]

    # ---------- worker ----------

    def _run(self) -> None:
        while True:
            step = None
            with self.lock:
                if not self.queue and self._repeat_plan and not self.cancel.is_set():
                    self.queue.extend(self._repeat_plan)  # loop until Stop, no silent cap
                if self.queue:
                    step = self.queue.pop(0)
                    self.active = True
                elif self.active:
                    self.active = False
                    self.node.halt()
            if step is None:
                time.sleep(0.05)
                continue
            try:
                self._dispatch(step)
            except Exception as exc:  # one bad step must never kill the worker
                self.node.get_logger().warn(f"step {step.get('primitive')} failed: {exc}")
                self.node.halt()

    def _dispatch(self, step: Dict) -> None:
        primitive = step.get("primitive")
        params = step.get("params") or {}
        handler = getattr(self, f"_do_{primitive}", None)
        if handler is None:
            return
        handler(params)

    def _sleep_tick(self) -> None:
        time.sleep(CONTROL_DT)

    def _running(self, deadline: float) -> bool:
        return not self.cancel.is_set() and time.time() < deadline

    # ---------- mobile primitives ----------

    def _do_wait(self, p: Dict) -> None:
        deadline = time.time() + float(p.get("duration", 1.0))
        while self._running(deadline):
            self._sleep_tick()

    def _do_stop(self, _p: Dict) -> None:
        self.node.halt()

    def _do_drive(self, p: Dict) -> None:
        speed = min(float(p.get("speed", 0.35)), MAX_LINEAR)
        if p.get("reverse"):
            speed = -speed
        distance = p.get("distance")
        until_front = p.get("until_front_within")
        safe = p.get("safe", True)
        deadline = time.time() + float(p.get("duration", 60.0))

        start_x, start_y, _ = self.node.state.base_2d()
        while self._running(deadline):
            x, y, _ = self.node.state.base_2d()
            if distance is not None and math.dist((x, y), (start_x, start_y)) >= float(distance):
                break
            if until_front is not None and self._scan_front <= float(until_front):
                break
            if safe and speed > 0 and self._scan_front <= OBSTACLE_STOP:
                break
            self.node.drive(speed, 0.0)
            self._sleep_tick()
        self.node.halt()

    def _do_turn(self, p: Dict) -> None:
        target = math.radians(float(p.get("angle_degrees", 90.0)))
        deadline = time.time() + min(30.0, abs(target) / 0.5 + 6.0)
        _, _, last_yaw = self.node.state.base_2d()
        turned = 0.0
        direction = 1.0 if target >= 0 else -1.0

        # Accumulate wrapped deltas: a raw yaw difference wraps at +-pi and would stop a
        # 270-degree turn early.
        while self._running(deadline) and abs(turned) < abs(target):
            _, _, yaw = self.node.state.base_2d()
            turned += wrap_pi(yaw - last_yaw)
            last_yaw = yaw
            remaining = abs(target) - abs(turned)
            self.node.drive(0.0, direction * min(MAX_ANGULAR, max(0.25, 2.0 * remaining)))
            self._sleep_tick()
        self.node.halt()

    def _aim(self, target_x: float, target_y: float, deadline: float, tolerance: float = 0.05) -> None:
        while self._running(deadline):
            x, y, yaw = self.node.state.base_2d()
            error = wrap_pi(math.atan2(target_y - y, target_x - x) - yaw)
            if abs(error) <= tolerance:
                break
            self.node.drive(0.0, max(-MAX_ANGULAR, min(MAX_ANGULAR, 2.0 * error)))
            self._sleep_tick()
        self.node.halt()

    def _do_face(self, p: Dict) -> None:
        deadline = time.time() + float(p.get("duration", 15.0))
        self._aim(float(p["x"]), float(p["y"]), deadline)

    def _do_go_to(self, p: Dict) -> None:
        target_x, target_y = float(p["x"]), float(p["y"])
        speed = min(float(p.get("speed", 0.4)), MAX_LINEAR)
        arrive = max(float(p.get("stop_distance", 0.0)), 0.0) + float(p.get("target_radius", 0.0))
        arrive = max(arrive, 0.12)
        deadline = time.time() + float(p.get("duration", 90.0))

        self._aim(target_x, target_y, deadline, tolerance=0.15)
        while self._running(deadline):
            x, y, yaw = self.node.state.base_2d()
            remaining = math.dist((x, y), (target_x, target_y))
            if remaining <= arrive:
                break
            error = wrap_pi(math.atan2(target_y - y, target_x - x) - yaw)
            angular = max(-MAX_ANGULAR, min(MAX_ANGULAR, 2.0 * error))
            # Turn in place while badly misaligned, then drive.
            linear = 0.0 if abs(error) > 0.6 else min(speed, 0.8 * remaining)
            if self._scan_front <= OBSTACLE_STOP:
                linear = 0.0
            self.node.drive(linear, angular)
            self._sleep_tick()
        self.node.halt()

    def _do_avoid_obstacles(self, p: Dict) -> None:
        speed = min(float(p.get("speed", 0.3)), MAX_LINEAR)
        deadline = time.time() + float(p.get("duration", 20.0))
        while self._running(deadline):
            ranges = self._scan_ranges
            if self._scan_front <= 0.6 and ranges:
                mid = len(ranges) // 2
                span = max(4, len(ranges) // 8)
                left = sum(ranges[mid + span : mid + 3 * span]) or 0.0
                right = sum(ranges[mid - 3 * span : mid - span]) or 0.0
                self.node.drive(0.0, 1.2 if left >= right else -1.2)
            else:
                self.node.drive(speed, 0.0)
            self._sleep_tick()
        self.node.halt()

    # ---------- arm primitives ----------

    def _send(self, joints: Dict[str, float], duration: float) -> None:
        if self.node.send_trajectory(joints, duration):
            deadline = time.time() + duration
            while self._running(deadline):
                self._sleep_tick()

    def _do_set_joints(self, p: Dict) -> None:
        current = self.node.state.snapshot_joints()
        relative = bool(p.get("relative"))
        targets: Dict[str, float] = {}
        for name, value in (p.get("joints") or {}).items():
            # describe_state reports revolute joints in degrees and prismatic in metres,
            # so only the revolute ones get converted.
            amount = math.radians(float(value)) if name in self.revolute else float(value)
            targets[name] = current.get(name, 0.0) + amount if relative else amount
        if targets:
            self._send(self.kin.clamp_to_limits(targets), float(p.get("duration", 1.5)))

    def _do_move_ee(self, p: Dict) -> None:
        x, y, z = (float(c) for c in p["position"][:3])
        solution, _error = self.kin.solve_best(x, y, z)
        if solution is not None:
            self._send(solution, float(p.get("duration", 2.0)))

    def _gripper(self, opening: float, duration: float = 0.6) -> None:
        jaws = self.kin.gripper(opening)
        if jaws:
            self._send(jaws, duration)

    def _do_release(self, _p: Dict) -> None:
        self.held_id = None
        self._gripper(self.kin.gripper_open)

    def _do_grasp(self, p: Dict) -> None:
        """Approach, close, then kinematically carry the object.

        Not a DetachableJoint: on Fortress that plugin cannot attach at runtime to a model
        spawned after the robot (re-attach landed in gz-sim 6.17, and <child_model> must be
        named at spawn time). So once the jaws close we record the object's offset from the
        tool and a 20 Hz servo keeps it welded via SetEntityPose. The viewport draws
        snapshot.objects[id], which is exactly this computed pose.
        """
        target_x, target_y = float(p.get("x", 0.0)), float(p.get("y", 0.0))
        radius = float(p.get("target_radius", 0.25))

        obj = self._nearest_dynamic(target_x, target_y, radius + 0.4)
        if obj is None:
            return

        self._gripper(self.kin.gripper_open, 0.4)
        self._do_go_to({"x": target_x, "y": target_y, "stop_distance": 0.38, "duration": 40.0})
        self._aim(target_x, target_y, time.time() + 8.0)

        local = self._world_to_base(obj["x"], obj["y"], obj["z"] + obj["h"] / 2.0)
        solution, _error = self.kin.solve(*local)
        if solution is None:
            solution, _error = self.kin.solve_best(*local)
        if solution is None:
            return

        self._send(solution, 1.5)
        self._gripper(self.kin.gripper_closed, 0.5)

        tool = self.kin.fk(self.node.state.snapshot_joints())
        self._held_offset = (local[0] - tool[0], local[1] - tool[1], local[2] - tool[2])
        self.held_id = obj["id"]

    def _do_flap(self, p: Dict) -> None:
        if not self.node.controller_ready():
            return  # else every iteration would block on wait_for_server
        amplitude = math.radians(float(p.get("amplitude_degrees", 35.0)))
        deadline = time.time() + float(p.get("duration", 3.0))
        shoulder = self.kin.arm_joints[1] if len(self.kin.arm_joints) > 1 else None
        if shoulder is None:
            return
        base = self.node.state.snapshot_joints().get(shoulder, 0.6)
        while self._running(deadline):
            phase = math.sin(2 * math.pi * float(p.get("freq", 1.0)) * time.time())
            self.node.send_trajectory({shoulder: base + amplitude * phase}, 0.25)
            time.sleep(0.25)

    def _do_circle(self, p: Dict) -> None:
        if not self.node.controller_ready():
            return  # else every iteration would block on wait_for_server
        amplitude = math.radians(float(p.get("amplitude_degrees", 30.0)))
        deadline = time.time() + float(p.get("duration", 4.0))
        while self._running(deadline):
            t = 2 * math.pi * float(p.get("freq", 0.5)) * time.time()
            if len(self.kin.arm_joints) < 2:
                return
            self.node.send_trajectory(
                {
                    self.kin.arm_joints[0]: amplitude * math.cos(t),
                    self.kin.arm_joints[1]: 0.6 + amplitude * 0.5 * math.sin(t),
                },
                0.25,
            )
            time.sleep(0.25)

    # ---------- helpers ----------

    def _nearest_dynamic(self, x: float, y: float, radius: float) -> Optional[Dict]:
        best, best_distance = None, radius
        for obj in self.world():
            if not obj.get("dynamic"):
                continue
            distance = math.dist((x, y), (float(obj["x"]), float(obj["y"])))
            if distance <= best_distance:
                best, best_distance = obj, distance
        return best

    def _world_to_base(self, x: float, y: float, z: float):
        bx, by, yaw = self.node.state.base_2d()
        dx, dy = x - bx, y - by
        cos_y, sin_y = math.cos(-yaw), math.sin(-yaw)
        return (dx * cos_y - dy * sin_y, dx * sin_y + dy * cos_y, z)

    def _base_to_world(self, x: float, y: float, z: float):
        bx, by, yaw = self.node.state.base_2d()
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        return (bx + x * cos_y - y * sin_y, by + x * sin_y + y * cos_y, z)

    def _servo_held(self) -> None:
        """Keep a grasped object welded to the tool at 20 Hz."""
        while True:
            held = self.held_id
            if held is None:
                time.sleep(0.1)
                continue
            tool = self.kin.fk(self.node.state.snapshot_joints())
            local = (
                tool[0] + self._held_offset[0],
                tool[1] + self._held_offset[1],
                tool[2] + self._held_offset[2],
            )
            wx, wy, wz = self._base_to_world(*local)
            _, _, yaw = self.node.state.base_2d()
            self.node.set_pose(held, wx, wy, wz, yaw)
            time.sleep(CONTROL_DT)
