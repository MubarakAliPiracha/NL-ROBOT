"""WorldObject -> SDF model strings.

Two things here are easy to get wrong and invisible when you do, because there is no
Gazebo GUI to look at:

1. `WorldObject.z` is the elevation of the object's BOTTOM face; an SDF `<pose>` is its
   CENTROID. Mixing them up buries every object half underground, and you would only
   notice via odd collision behaviour.
2. Non-static bodies need a real `<inertial>`. A missing or zero inertia in Fortress
   gives you a link that either explodes or is silently ignored.

Shape fidelity is deliberately approximate: cone/pyramid/wedge have no SDF primitive, so
they become their nearest primitive and we emit a warning. The frontend draws the true
hulls from lib/world.ts, so the approximation is never visible -- the Gazebo copy exists
only so the robot collides with something.
"""

import math
from typing import Dict, List, Tuple

# kind -> (sdf primitive, is_approximate)
SHAPE_MAP = {
    "box": ("box", False),
    "cylinder": ("cylinder", False),
    "sphere": ("sphere", False),
    "cone": ("cylinder", True),
    "pyramid": ("box", True),
    "wedge": ("box", True),
}

# Shape vocabulary shared with the frontend (lib/world.ts) and world_ops.py.
KINDS = tuple(SHAPE_MAP)

DEFAULT_MASS = 1.0


def hex_to_rgba(colour: str) -> str:
    value = (colour or "#9aa3b2").lstrip("#")
    if len(value) != 6:
        value = "9aa3b2"
    r, g, b = (int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return f"{r:.3f} {g:.3f} {b:.3f} 1"


def centroid_z(obj: Dict) -> float:
    """Convert bottom-face elevation to centroid height."""
    return float(obj["z"]) + float(obj["h"]) / 2.0


def box_inertia(mass: float, w: float, d: float, h: float) -> Tuple[float, float, float]:
    return (
        mass * (d * d + h * h) / 12.0,
        mass * (w * w + h * h) / 12.0,
        mass * (w * w + d * d) / 12.0,
    )


def _geometry_xml(obj: Dict) -> str:
    primitive, _ = SHAPE_MAP.get(obj.get("kind", "box"), ("box", False))
    w, d, h = float(obj["w"]), float(obj["d"]), float(obj["h"])

    if primitive == "sphere":
        return f"<sphere><radius>{max(w, d, h) / 2.0:.4f}</radius></sphere>"
    if primitive == "cylinder":
        # A cone becomes a slimmer cylinder so it occupies a similar average footprint.
        radius = max(w, d) / (4.0 if obj.get("kind") == "cone" else 2.0)
        return f"<cylinder><radius>{radius:.4f}</radius><length>{h:.4f}</length></cylinder>"
    if obj.get("kind") == "pyramid":
        w, d = w * 0.7, d * 0.7
    return f"<box><size>{w:.4f} {d:.4f} {h:.4f}</size></box>"


def model_sdf(obj: Dict) -> str:
    """A complete <sdf> document for one world object."""
    name = obj["id"]
    geometry = _geometry_xml(obj)
    rgba = hex_to_rgba(obj.get("color", ""))
    dynamic = bool(obj.get("dynamic"))
    mass = float(obj.get("mass", DEFAULT_MASS))
    ixx, iyy, izz = box_inertia(mass, float(obj["w"]), float(obj["d"]), float(obj["h"]))

    inertial = (
        f"<inertial><mass>{mass:.4f}</mass>"
        f"<inertia><ixx>{ixx:.6f}</ixx><iyy>{iyy:.6f}</iyy><izz>{izz:.6f}</izz>"
        f"<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>"
    )

    return (
        '<?xml version="1.0" ?>'
        '<sdf version="1.8">'
        f'<model name="{name}">'
        f"<static>{'false' if dynamic else 'true'}</static>"
        '<link name="link">'
        f"{inertial if dynamic else ''}"
        f'<collision name="collision"><geometry>{geometry}</geometry></collision>'
        f'<visual name="visual"><geometry>{geometry}</geometry>'
        f"<material><ambient>{rgba}</ambient><diffuse>{rgba}</diffuse></material>"
        "</visual>"
        "</link>"
        "</model>"
        "</sdf>"
    )


def pose_of(obj: Dict) -> Tuple[float, float, float, float]:
    """(x, y, centroid_z, yaw_radians) ready for an SDF pose."""
    return (
        float(obj["x"]),
        float(obj["y"]),
        centroid_z(obj),
        math.radians(float(obj.get("yaw", 0.0))),
    )


def approximation_warnings(objects: List[Dict]) -> List[str]:
    kinds = {
        obj.get("kind")
        for obj in objects
        if SHAPE_MAP.get(obj.get("kind", "box"), ("box", False))[1]
    }
    return [
        f"'{kind}' has no exact Gazebo primitive - simulated as its nearest shape "
        f"(it still looks correct in the 3D view)."
        for kind in sorted(k for k in kinds if k)
    ]
