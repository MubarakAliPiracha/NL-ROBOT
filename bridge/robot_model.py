"""Read a URDF and derive everything the bridge needs to drive that robot.

This is what makes the system robot-agnostic rather than nlbot-specific: joint names,
limits, which joints are wheels, which are the gripper, the arm chain and its link
lengths, and the base footprint all come from the file, not from constants.

The arm chain is reduced to a turret + planar 3R approximation so the closed-form IK in
kinematics.py can drive an arm it has never seen. That is exact for arms built that way
(nlbot) and a good approximation for arms with a small elbow offset (OpenMANIPULATOR-X).
"""

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

WHEEL_HINTS = ("wheel",)
GRIPPER_HINTS = ("gripper", "finger", "grip")


def _xyz(element: Optional[ET.Element]) -> Tuple[float, float, float]:
    if element is None:
        return (0.0, 0.0, 0.0)
    parts = [float(v) for v in (element.get("xyz") or "0 0 0").split()]
    return tuple(parts + [0.0] * (3 - len(parts)))[:3]


@dataclass
class RobotModel:
    name: str
    joints: List[Dict] = field(default_factory=list)
    wheels: List[str] = field(default_factory=list)
    gripper_joints: List[str] = field(default_factory=list)
    arm_joints: List[str] = field(default_factory=list)
    arm_base: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    link_lengths: Tuple[float, float, float] = (0.25, 0.22, 0.09)
    gripper_range: Tuple[float, float] = (0.0, 0.03)
    footprint: Tuple[float, float, float] = (0.4, 0.3, 0.3)
    mimics: List[str] = field(default_factory=list)
    sensors: List[Dict] = field(default_factory=list)

    @property
    def movable(self) -> List[Dict]:
        return [j for j in self.joints if j["type"] != "fixed"]

    @property
    def reach(self) -> float:
        return sum(self.link_lengths)

    @property
    def max_opening(self) -> float:
        return 2 * self.gripper_range[1] + 0.014

    def home(self) -> Dict[str, float]:
        """A safe tucked pose: shoulder up, elbow folded, wrist levelled."""
        defaults = [0.0, 0.6, -1.2, -0.5, 0.0, 0.0]
        return {name: defaults[i] if i < len(defaults) else 0.0
                for i, name in enumerate(self.arm_joints)}

    def limits(self, joint_name: str) -> Tuple[float, float]:
        for joint in self.joints:
            if joint["name"] == joint_name:
                lo, hi = joint["lower_limit"], joint["upper_limit"]
                if lo is not None and hi is not None:
                    return (lo, hi)
        return (-math.pi, math.pi)


def load(urdf_path: str) -> RobotModel:
    root = ET.parse(urdf_path).getroot()
    model = RobotModel(name=root.get("name") or "robot")

    joint_elements = {j.get("name"): j for j in root.findall("joint")}
    model.mimics = [n for n, e in joint_elements.items() if e.find("mimic") is not None]
    for index, (joint_name, element) in enumerate(joint_elements.items()):
        kind = element.get("type")
        limit = element.find("limit")
        lower = float(limit.get("lower")) if limit is not None and limit.get("lower") else None
        upper = float(limit.get("upper")) if limit is not None and limit.get("upper") else None
        model.joints.append({
            "index": index, "name": joint_name, "type": kind,
            "lower_limit": lower, "upper_limit": upper,
        })

        lowered = (joint_name or "").lower()
        if kind == "continuous" and any(h in lowered for h in WHEEL_HINTS):
            model.wheels.append(joint_name)
        elif kind == "prismatic" and any(h in lowered for h in GRIPPER_HINTS):
            model.gripper_joints.append(joint_name)
        elif kind in ("revolute", "prismatic"):
            model.arm_joints.append(joint_name)

    # A mimic follows its driver automatically; commanding it fails the interface claim.
    model.gripper_joints = [j for j in model.gripper_joints if j not in model.mimics]
    model.arm_joints = [j for j in model.arm_joints if j not in model.mimics]
    if model.gripper_joints:
        lower, upper = model.limits(model.gripper_joints[0])
        model.gripper_range = (lower, upper)

    _derive_arm_geometry(root, joint_elements, model)
    _derive_footprint(root, model)
    model.sensors = parse_sensors(root)
    return model


def parse_sensors(root: ET.Element) -> List[Dict]:
    """Sensors declared in the URDF's <gazebo> extension blocks.

    Core URDF has no sensor concept -- lidar/camera/IMU live in <gazebo reference=...>
    wrappers, which is also why a plain URDF viewer never shows them.
    """
    found = []
    for block in root.findall("gazebo"):
        link = block.get("reference") or "?"
        for sensor in block.iter("sensor"):
            kind = sensor.get("type") or "?"
            topic = sensor.findtext("topic") or kind
            entry = {"name": sensor.get("name") or kind, "type": kind,
                     "link": link, "topic": "/" + topic.lstrip("/")}
            if kind == "gpu_lidar":
                rng = sensor.find(".//range")
                if rng is not None:
                    entry["range_m"] = [float(rng.findtext("min") or 0),
                                        float(rng.findtext("max") or 0)]
                samples = sensor.findtext(".//horizontal/samples")
                if samples:
                    entry["samples"] = int(samples)
            rate = sensor.findtext("update_rate")
            if rate:
                entry["rate_hz"] = float(rate)
            found.append(entry)
    return found


def _derive_arm_geometry(root: ET.Element, joint_elements: Dict, model: RobotModel) -> None:
    """Accumulate joint origins along the arm chain into three effective link lengths."""
    if len(model.arm_joints) < 2:
        return

    origins = []
    for joint_name in model.arm_joints:
        element = joint_elements.get(joint_name)
        origins.append(_xyz(element.find("origin")) if element is not None else (0.0, 0.0, 0.0))

    # First arm joint's origin is where the arm meets the base. Accumulate it with any
    # fixed offsets already baked into the chain's first link.
    model.arm_base = origins[0]

    def span(offset) -> float:
        return math.sqrt(offset[0] ** 2 + offset[1] ** 2 + offset[2] ** 2)

    spans = [span(o) for o in origins[1:]]
    # Fold everything past the third moving joint into the wrist length.
    l1 = spans[0] if len(spans) > 0 else 0.25
    l2 = spans[1] if len(spans) > 1 else 0.22
    l3 = sum(spans[2:]) if len(spans) > 2 else 0.09
    if min(l1, l2, l3) <= 1e-4:  # degenerate chain; keep the defaults
        return
    model.link_lengths = (round(l1, 4), round(l2, 4), round(l3, 4))


def _derive_footprint(root: ET.Element, model: RobotModel) -> None:
    """Base box dimensions, for the LLM's scale_guide."""
    for link in root.findall("link"):
        if link.get("name") not in ("base_link", "base_footprint"):
            continue
        box = link.find(".//collision/geometry/box") or link.find(".//visual/geometry/box")
        if box is not None:
            size = [float(v) for v in (box.get("size") or "").split()]
            if len(size) == 3:
                model.footprint = tuple(size)
                return
    # No box base (TurtleBot3 uses a mesh): fall back to its published footprint.
    model.footprint = (0.28, 0.28, 0.40)
