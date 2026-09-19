"""Synthesized 360-degree laser scan.

Why this exists: Gazebo's `gpu_lidar` needs a rendering backend. There is no GPU and no
display inside the container, so a rendering sensor would publish nothing at all. Instead
we 2D-raycast the authored world list and publish a genuine `sensor_msgs/LaserScan`.

That is not a workaround so much as a trade: the scan becomes *deterministic*, which for a
robot-testing product is a feature -- the same world always produces the same scan, so a
regression either passes or fails for a real reason. Swapping in `gpu_lidar` on a GPU
machine is a URDF edit, and nothing downstream of /scan changes.

The geometry here is pure numpy and has no ROS import, so it is testable anywhere.
"""

import math
from typing import Dict, List, Sequence

import numpy as np

# Matches the original PyBullet rover's sensor so the viewport fan looks the same.
N_RAYS = 180
ANGLE_MIN = -math.pi
ANGLE_INCREMENT = 2 * math.pi / N_RAYS
RANGE_MAX = 8.0
RANGE_MIN = 0.05
LASER_HEIGHT = 0.18  # laser_joint z in nlbot.urdf

# World kinds whose 2D footprint is a circle rather than a rectangle.
_ROUND_KINDS = {"cylinder", "cone", "sphere"}


def _ray_directions(yaw: float) -> np.ndarray:
    angles = yaw + ANGLE_MIN + ANGLE_INCREMENT * np.arange(N_RAYS)
    return np.stack([np.cos(angles), np.sin(angles)], axis=1)


def _hits_circle(origin: np.ndarray, dirs: np.ndarray, centre, radius: float) -> np.ndarray:
    """Distance along each ray to a circle, or inf."""
    oc = origin - np.asarray(centre, dtype=float)
    b = 2.0 * (dirs @ oc)
    c = float(oc @ oc) - radius * radius
    disc = b * b - 4.0 * c
    out = np.full(len(dirs), np.inf)
    hit = disc >= 0.0
    if not hit.any():
        return out
    sqrt_disc = np.sqrt(disc[hit])
    near = (-b[hit] - sqrt_disc) / 2.0
    far = (-b[hit] + sqrt_disc) / 2.0
    # If the sensor sits inside the circle the near root is negative; use the far one.
    dist = np.where(near > 0.0, near, far)
    dist = np.where(dist > 0.0, dist, np.inf)
    out[hit] = dist
    return out


def _hits_segment(origin: np.ndarray, dirs: np.ndarray, p1, p2) -> np.ndarray:
    """Distance along each ray to a line segment, or inf."""
    p1 = np.asarray(p1, dtype=float)
    edge = np.asarray(p2, dtype=float) - p1
    denom = dirs[:, 0] * edge[1] - dirs[:, 1] * edge[0]
    out = np.full(len(dirs), np.inf)
    parallel = np.abs(denom) < 1e-12
    safe = np.where(parallel, 1.0, denom)

    rel = p1 - origin
    t = (rel[0] * edge[1] - rel[1] * edge[0]) / safe          # along the ray
    u = (rel[0] * dirs[:, 1] - rel[1] * dirs[:, 0]) / safe    # along the segment

    valid = (~parallel) & (t > 0.0) & (u >= 0.0) & (u <= 1.0)
    out[valid] = t[valid]
    return out


def _rect_corners(obj: Dict) -> List[np.ndarray]:
    half_w, half_d = obj["w"] / 2.0, obj["d"] / 2.0
    yaw = math.radians(obj.get("yaw", 0.0))
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    centre = np.array([obj["x"], obj["y"]], dtype=float)
    local = [(-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)]
    return [
        centre + np.array([lx * cos_y - ly * sin_y, lx * sin_y + ly * cos_y])
        for lx, ly in local
    ]


def _intersects_laser_plane(obj: Dict) -> bool:
    """True if the object straddles the laser height. `z` is the bottom face."""
    bottom = float(obj.get("z", 0.0))
    return bottom <= LASER_HEIGHT <= bottom + float(obj.get("h", 0.0))


def raycast(world: Sequence[Dict], x: float, y: float, yaw: float) -> List[float]:
    """Ranges for a full 360-degree fan from (x, y) with heading `yaw`."""
    origin = np.array([x, y], dtype=float)
    dirs = _ray_directions(yaw)
    best = np.full(N_RAYS, np.inf)

    for obj in world:
        if not _intersects_laser_plane(obj):
            continue
        if obj.get("kind") in _ROUND_KINDS:
            radius = max(float(obj["w"]), float(obj["d"])) / 2.0
            best = np.minimum(best, _hits_circle(origin, dirs, (obj["x"], obj["y"]), radius))
        else:
            corners = _rect_corners(obj)
            for i in range(4):
                best = np.minimum(
                    best, _hits_segment(origin, dirs, corners[i], corners[(i + 1) % 4])
                )

    best = np.where(np.isfinite(best), best, RANGE_MAX)
    return np.clip(best, RANGE_MIN, RANGE_MAX).tolist()


def snapshot_sensor(world: Sequence[Dict], x: float, y: float, z: float, yaw: float) -> Dict:
    """The `sensor` block of the WebSocket frame.

    `a0` is robot-relative -- the viewport computes cos(yaw + a0 + i*da), so the heading
    is supplied separately in `yaw` (verified in web/components/scene-viewport.tsx).
    """
    ranges = raycast(world, x, y, yaw)
    return {
        "origin": [round(x, 3), round(y, 3), round(z, 3)],
        "yaw": round(yaw, 4),
        "a0": ANGLE_MIN,
        "da": ANGLE_INCREMENT,
        "range": RANGE_MAX,
        "dist": [round(r, 3) for r in ranges],
        "front": round(ranges[N_RAYS // 2], 3),
    }
