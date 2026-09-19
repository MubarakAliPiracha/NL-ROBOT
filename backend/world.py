"""User-built world objects (Tinkercad-style shapes) as static PyBullet bodies.

Sizes are full extents in metres: w along x, d along y, h along z. `z` is the
elevation of the object's bottom face. The convex-hull vertex lists here must
match `hullPoints` in lib/world.ts so the viewport shows what physics collides with.
"""

import math
from typing import Dict, List

import pybullet as p

KINDS = ("box", "cylinder", "sphere", "cone", "pyramid", "wedge")
CONE_SEGMENTS = 32


def hull_points(kind: str, w: float, d: float, h: float) -> List[List[float]]:
    if kind == "cone":
        ring = [
            [w / 2 * math.cos(2 * math.pi * i / CONE_SEGMENTS), d / 2 * math.sin(2 * math.pi * i / CONE_SEGMENTS), -h / 2]
            for i in range(CONE_SEGMENTS)
        ]
        return ring + [[0.0, 0.0, h / 2]]
    if kind == "pyramid":
        return [[-w / 2, -d / 2, -h / 2], [w / 2, -d / 2, -h / 2], [w / 2, d / 2, -h / 2], [-w / 2, d / 2, -h / 2], [0.0, 0.0, h / 2]]
    if kind == "wedge":  # ramp rising toward +x
        return [
            [-w / 2, -d / 2, -h / 2], [w / 2, -d / 2, -h / 2], [w / 2, -d / 2, h / 2],
            [-w / 2, d / 2, -h / 2], [w / 2, d / 2, -h / 2], [w / 2, d / 2, h / 2],
        ]
    raise ValueError(kind)


def volume(kind: str, w: float, d: float, h: float) -> float:
    return {
        "box": w * d * h,
        "cylinder": math.pi / 4 * w * d * h,
        "sphere": math.pi / 6 * w * w * w,
        "cone": math.pi / 12 * w * d * h,
        "pyramid": w * d * h / 3,
        "wedge": w * d * h / 2,
    }[kind]


def create_body(obj: Dict) -> int:
    kind = obj["kind"]
    w, d, h = (max(0.01, float(obj[k])) for k in ("w", "d", "h"))
    if kind == "box":
        shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=[w / 2, d / 2, h / 2])
    elif kind == "cylinder":
        shape = p.createCollisionShape(p.GEOM_CYLINDER, radius=w / 2, height=h)
    elif kind == "sphere":
        shape = p.createCollisionShape(p.GEOM_SPHERE, radius=w / 2)
    elif kind in KINDS:
        shape = p.createCollisionShape(p.GEOM_MESH, vertices=hull_points(kind, w, d, h))
    else:
        raise ValueError(f"Unknown shape kind: {kind}")
    orn = p.getQuaternionFromEuler([0, 0, math.radians(float(obj.get("yaw", 0.0)))])
    pos = [float(obj["x"]), float(obj["y"]), float(obj["z"]) + h / 2]
    mass = 0.0
    if obj.get("dynamic"):
        mass = float(obj.get("mass") or min(10.0, max(0.1, volume(kind, w, d, h) * 20.0)))
    body = p.createMultiBody(baseMass=mass, baseCollisionShapeIndex=shape, basePosition=pos, baseOrientation=orn)
    if mass > 0:
        p.changeDynamics(body, -1, lateralFriction=0.8, restitution=0.5 if kind == "sphere" else 0.15)
    return body
