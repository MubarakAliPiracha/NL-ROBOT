"""Validated edits to the world (add / update / remove / clear), used when the AI builds or changes a map."""

import math
import random
import string
from typing import Dict, List, Tuple

from world import KINDS

COLORS = {
    "red": "#e5403b", "orange": "#f28c1b", "yellow": "#f2c21b", "green": "#3aa655", "blue": "#2f8de4",
    "purple": "#8e44c2", "pink": "#e85d9c", "white": "#f4f6fa", "black": "#2b2f38", "gray": "#8a94a6",
    "grey": "#8a94a6", "brown": "#8b5a3c", "teal": "#1fa7a0",
}
DEFAULT_COLOR = {
    "box": "#e5403b", "cylinder": "#f28c1b", "sphere": "#2f8de4", "cone": "#8e44c2", "pyramid": "#f2c21b", "wedge": "#3aa655",
}
MAX_OBJECTS = 80


def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) else max(lo, min(hi, f))


def _color(v, kind: str) -> str:
    if isinstance(v, str):
        c = v.strip().lower()
        if c in COLORS:
            return COLORS[c]
        if len(c) == 7 and c.startswith("#"):
            return c
    return DEFAULT_COLOR[kind]


def _new_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=7))


def _find(world: List[Dict], name: str):
    n = str(name).strip().lower()
    for o in world:
        if o["name"].lower() == n:
            return o
    for o in world:
        if n and n in o["name"].lower():
            return o
    return None


def _unique(world: List[Dict], base: str) -> str:
    names = {o["name"].lower() for o in world}
    if base.lower() not in names:
        return base
    i = 2
    while f"{base} {i}".lower() in names:
        i += 1
    return f"{base} {i}"


def make_object(spec: Dict, world: List[Dict]) -> Dict:
    kind = str(spec.get("kind", "box")).lower()
    if kind not in KINDS:
        kind = "box"
    w = _num(spec.get("w"), 1.0, 0.02, 150)
    d = _num(spec.get("d"), 1.0, 0.02, 150)
    h = _num(spec.get("h"), 1.0, 0.02, 60)
    if kind == "sphere":
        d = h = w
    elif kind in ("cylinder", "cone"):
        d = w
    return {
        "id": _new_id(),
        "kind": kind,
        "name": _unique(world, str(spec.get("name") or kind.capitalize())[:40]),
        "x": _num(spec.get("x"), 2.0, -300, 300),
        "y": _num(spec.get("y"), 0.0, -300, 300),
        "z": _num(spec.get("z"), 0.0, 0, 40),
        "w": w, "d": d, "h": h,
        "yaw": _num(spec.get("yaw"), 0.0, -360, 360),
        "color": _color(spec.get("color"), kind),
        "dynamic": bool(spec.get("dynamic", False)),
        **({"mass": _num(spec.get("mass"), 1.0, 0.05, 200)} if spec.get("mass") else {}),
    }


def apply_ops(world: List[Dict], ops: Dict) -> Tuple[List[Dict], List[str]]:
    """Return (new_world, warnings). Never raises on bad AI output; skips what it can't use."""
    warnings: List[str] = []
    new = [] if ops.get("clear") else [dict(o) for o in world]

    for name in ops.get("remove") or []:
        target = _find(new, name)
        if target:
            new.remove(target)
        else:
            warnings.append(f"Couldn't remove '{name}': no such object.")

    for spec in ops.get("add") or []:
        if not isinstance(spec, dict):
            continue
        if len(new) >= MAX_OBJECTS:
            warnings.append(f"Stopped adding shapes at the {MAX_OBJECTS}-object limit.")
            break
        new.append(make_object(spec, new))
    for spec in ops.get("update") or []:
        if not isinstance(spec, dict) or "name" not in spec:
            continue
        target = _find(new, spec["name"])
        if not target:
            warnings.append(f"Couldn't update '{spec['name']}': no such object.")
            continue
        merged = {**target, **{k: v for k, v in spec.items() if k != "name"}}
        fixed = make_object({**merged, "name": target["name"]}, [o for o in new if o is not target])
        fixed["id"] = target["id"]
        target.update(fixed)

    return new, warnings
