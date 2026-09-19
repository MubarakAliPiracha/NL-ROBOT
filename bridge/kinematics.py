"""Closed-form FK/IK for a turret + 3R planar arm.

The arm is treated as a 1-DOF turret (yaw about Z) plus three in-plane joints. That shape
is analytically solvable, which is why this file exists instead of a MoveIt config or an
ikpy dependency.

Link lengths and joint names come from the loaded URDF (see robot_model.py), so the same
solver drives nlbot and the imported TurtleBot3 + OpenMANIPULATOR-X. It is exact for arms
actually built this way and a close approximation where the real arm has a small elbow
offset.

Pure trigonometry on floats -- no ROS, no numpy -- so it is testable anywhere.
"""

import math
from typing import Dict, Optional, Tuple

# Approach angles tried by solve_best, nearest-to-straight-down first.
_PITCH_LADDER = [-math.pi / 2, -1.2, -0.9, -0.6, -0.3, 0.0, 0.3, 0.6, -1.8, -2.1]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class Kinematics:
    """FK/IK bound to one robot's geometry."""

    def __init__(self, model) -> None:
        self.model = model
        self.arm_joints = list(model.arm_joints)[:4]
        self.gripper_joints = list(model.gripper_joints)
        self.l1, self.l2, self.l3 = model.link_lengths
        # Shoulder sits at the first arm joint's origin relative to base_link.
        self.arm_base = model.arm_base
        self.reach = self.l1 + self.l2 + self.l3
        self.gripper_open = model.gripper_range[1]
        self.gripper_closed = model.gripper_range[0] + 0.002
        self.max_opening = model.max_opening
        self.home = model.home()

    # ---------- limits ----------

    def clamp_to_limits(self, joints: Dict[str, float]) -> Dict[str, float]:
        return {name: clamp(angle, *self.model.limits(name)) for name, angle in joints.items()}

    # ---------- forward ----------

    def fk(self, joints: Dict[str, float]) -> Tuple[float, float, float]:
        """Tool centre point in base_link coordinates, from arm joint angles (radians)."""
        if len(self.arm_joints) < 4:
            return self.arm_base
        yaw = joints.get(self.arm_joints[0], 0.0)
        shoulder = joints.get(self.arm_joints[1], 0.0)
        elbow = joints.get(self.arm_joints[2], 0.0)
        wrist = joints.get(self.arm_joints[3], 0.0)

        a1 = shoulder
        a2 = shoulder + elbow
        a3 = shoulder + elbow + wrist
        radial = self.l1 * math.cos(a1) + self.l2 * math.cos(a2) + self.l3 * math.cos(a3)
        vertical = self.l1 * math.sin(a1) + self.l2 * math.sin(a2) + self.l3 * math.sin(a3)

        return (
            self.arm_base[0] + radial * math.cos(yaw),
            self.arm_base[1] + radial * math.sin(yaw),
            self.arm_base[2] + vertical,
        )

    # ---------- inverse ----------

    def solve(
        self, x: float, y: float, z: float, pitch: float = -math.pi / 2
    ) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
        """Arm joints putting the TCP at (x, y, z) in base_link, or (None, reason).

        The reason string goes straight into CommandResult.warnings, which the UI renders.
        """
        if len(self.arm_joints) < 4:
            return None, "This robot has no 4-joint arm chain."

        # Measure from the arm base, not the robot origin: the turret sits forward of
        # base_link, so hypot(x, y) - arm_base_x is only correct on the y = 0 line.
        dx = x - self.arm_base[0]
        dy = y - self.arm_base[1]
        yaw = math.atan2(dy, dx)
        radial = math.hypot(dx, dy)
        vertical = z - self.arm_base[2]

        wrist_r = radial - self.l3 * math.cos(pitch)
        wrist_z = vertical - self.l3 * math.sin(pitch)

        cos_elbow = (wrist_r ** 2 + wrist_z ** 2 - self.l1 ** 2 - self.l2 ** 2) / (2 * self.l1 * self.l2)
        if abs(cos_elbow) > 1.0:
            return None, (
                f"Target ({x:.2f}, {y:.2f}, {z:.2f}) is out of the arm's reach "
                f"(about {self.reach:.2f} m from the arm base)."
            )

        elbow = -math.acos(clamp(cos_elbow, -1.0, 1.0))  # elbow-up branch
        shoulder = math.atan2(wrist_z, wrist_r) - math.atan2(
            self.l2 * math.sin(elbow), self.l1 + self.l2 * math.cos(elbow)
        )
        wrist = pitch - shoulder - elbow

        solution = dict(zip(self.arm_joints, (yaw, shoulder, elbow, wrist)))

        # A clamped solution is a wrong solution -- say so rather than moving elsewhere.
        clamped = self.clamp_to_limits(solution)
        for name, angle in solution.items():
            if abs(clamped[name] - angle) > 1e-6:
                return None, f"Target ({x:.2f}, {y:.2f}, {z:.2f}) needs {name} beyond its limit."
        return clamped, None

    def solve_best(
        self, x: float, y: float, z: float
    ) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
        """Like `solve`, but tries a ladder of approach angles before giving up.

        `move_ee` only cares where the tool ends up, not how it is tilted, so refusing a
        reachable point purely because a straight-down approach fails would be too strict.
        `grasp` still uses `solve` with an explicit pitch.
        """
        last_error = None
        for pitch in _PITCH_LADDER:
            solution, error = self.solve(x, y, z, pitch)
            if solution is not None:
                return solution, None
            last_error = error
        return None, last_error

    def reachable(self, x: float, y: float, z: float) -> bool:
        return self.solve_best(x, y, z)[0] is not None

    def gripper(self, opening: float) -> Dict[str, float]:
        return {name: opening for name in self.gripper_joints}
