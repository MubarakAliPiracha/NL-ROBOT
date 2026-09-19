"""Deterministic natural-language parser for wheeled robots.

Understands things like:
  "drive forward until you see the wall, then turn left"
  "move forward and if it sees a block turn right 45 degrees"
  "go 2 meters, turn around, drive back for 3 seconds, repeat"

Produces PoC-style plans: {"plan": [{"primitive": ..., "params": ...}], "repeat": bool}.
"""

import re
from typing import Dict, List, Optional

NUM = r"(\d+(?:\.\d+)?)"
OBJ = r"(?:walls?|obstacles?|objects?|blocks?|boxe?s?|cubes?|barriers?|cylinders?|spheres?|cones?|ramps?|something|anything|things?|pyramids?|wedges?)"
SENSE_VERB = (
    r"(?:can\s+)?(?:see|sees|seeing|detect|detects|sense|senses|find|finds|hit|hits|reach|reaches|touch|touches|"
    r"meet|meets|encounter|encounters|approach|approaches|bump(?:s)?\s+into|run(?:s)?\s+into|come(?:s)?\s+(?:to|across)|"
    r"get(?:s)?\s+(?:to|close\s+to|near)|(?:is|are)\s+(?:near|close\s+to|in\s+front\s+of|ahead)|near|close\s+to|is|are)"
)
SENSE = re.compile(
    r"(?:until|till|unless|if|when|once|as\s+soon\s+as|whenever|before)\s+"
    r"(?:you(?:'re|\s+are)?|it|the\s+(?:robot|car|rover|vehicle)|we|there\s+(?:is|are))?\s*"
    + SENSE_VERB
    + r"?\s*(?:a|an|the|any|some|that)?\s*(?:\w+\s+)?"
    + OBJ
    + r"(?:\s+(?:in\s+front|ahead))?"
)
SENSE_NEAR = re.compile(
    r"(?:until|till|when|if|once|as\s+soon\s+as)\s+(?:you(?:'re|\s+are)?|it(?:'s|\s+is)?|the\s+\w+\s+is)\s*"
    r"(?:within|less\s+than|closer\s+than|at)\s+" + NUM + r"\s*(?:meters?|metres?|m|cm|centimeters?|feet|foot|ft)\s+"
    r"(?:of|from|to)\s+(?:a|an|the)?\s*(?:\w+\s+)?" + OBJ
)
UNIT_M = {"m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0, "cm": 0.01, "centimeter": 0.01,
          "centimeters": 0.01, "ft": 0.3048, "feet": 0.3048, "foot": 0.3048}
DIST_RE = re.compile(NUM + r"\s*(meters?|metres?|m|cm|centimeters?|feet|foot|ft)\b")
DUR_RE = re.compile(NUM + r"\s*(seconds?|secs?|s|minutes?|mins?)\b")
ANGLE_RE = re.compile(NUM + r"\s*(?:degrees?|deg|°)")
SPLIT_RE = re.compile(r"\s*(?:,|;|\.|\band\s+then\b|\bthen\b|\bafter\s+that\b|\band\b)\s*")
DEFAULT_STOP_DISTANCE = 0.6


def _meters(text: str) -> Optional[float]:
    m = DIST_RE.search(text)
    return float(m.group(1)) * UNIT_M[m.group(2)] if m else None


def _seconds(text: str) -> Optional[float]:
    m = DUR_RE.search(text)
    if not m:
        return None
    return float(m.group(1)) * (60.0 if m.group(2).startswith("min") else 1.0)


def _clause_to_action(clause: str) -> Optional[Dict]:
    c = clause.strip()
    if not c:
        return None
    turn_like = re.search(r"\b(turn|rotate|spin|steer|veer|swerve|pivot|u-turn)\b", c) or re.search(
        r"\b(go|head|move)\s+(left|right)\b", c
    )
    if turn_like:
        if re.search(r"\b(around|back|u-turn|about)\b", c):
            angle = 180.0
        else:
            m = ANGLE_RE.search(c)
            angle = float(m.group(1)) if m else 90.0
            if re.search(r"\bquarter\b", c):
                angle = 90.0
            if re.search(r"\bhalf\b", c):
                angle = 180.0
        if re.search(r"\bright\b|clockwise", c) and not re.search(r"counter|anti", c):
            angle = -angle
        return {"primitive": "turn", "params": {"angle_degrees": angle}}

    if re.search(r"\b(drive|driving|go|going|move|moving|head|heading|roll|advance|travel|run|proceed|continue|reverse|back\s*up|backup|forward|ahead)\b", c):
        params: Dict = {}
        dist = _meters(c)
        dur = _seconds(c)
        if dist is not None:
            params["distance"] = dist
        elif dur is not None:
            params["duration"] = dur
        if re.search(r"\b(back|backward|backwards|reverse|backup|back\s*up)\b", c):
            params["reverse"] = True
        return {"primitive": "drive", "params": params}

    if re.search(r"\b(stop|halt|brake|wait|pause|rest)\b", c):
        dur = _seconds(c)
        return {"primitive": "wait", "params": {"duration": dur if dur is not None else 0.5}}
    return None


def _clauses(segment: str) -> List[Dict]:
    out = []
    for piece in SPLIT_RE.split(segment):
        action = _clause_to_action(piece)
        if action:
            out.append(action)
    return out


def parse(text: str) -> Optional[Dict]:
    t = " " + text.lower().strip() + " "
    t = re.sub(r"\bthe robot\b|\bplease\b", " ", t)
    repeat = bool(re.search(r"\b(repeat|forever|over\s+and\s+over|keep\s+doing|loop|continuously|on\s+repeat)\b", t))
    t = re.sub(r"\b(and\s+)?(repeat(?:\s+(?:that|this|it))?|forever|over\s+and\s+over|keep\s+doing\s+(?:that|this|it)|continuously|on\s+repeat)\b", " ", t)

    if re.search(r"\b(avoid|dodge)\b.*\b(obstacles?|walls?|objects?)\b|\b(wander|roam|explore|patrol)\b", t):
        return {"plan": [{"primitive": "avoid_obstacles", "params": {"threshold": DEFAULT_STOP_DISTANCE}}], "repeat": False}

    sense = SENSE_NEAR.search(t) or SENSE.search(t)
    if sense:
        before, after = t[: sense.start()], t[sense.end():]
        tail = t[sense.start(): sense.end() + 30]
        stop_at = _meters(tail) or DEFAULT_STOP_DISTANCE
        plan = _clauses(before)
        last_drive = next((i for i in range(len(plan) - 1, -1, -1) if plan[i]["primitive"] == "drive"), None)
        if last_drive is None:
            plan.append({"primitive": "drive", "params": {}})
            last_drive = len(plan) - 1
        plan[last_drive]["params"]["until_within"] = stop_at
        plan.extend(_clauses(after))
    else:
        plan = _clauses(t)

    if not plan:
        return None
    return {"plan": plan, "repeat": repeat}
