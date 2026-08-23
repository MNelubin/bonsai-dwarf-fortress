"""The anti-forgery gate, schema-aware.

The agent proposes; this module judges; trusted Lua acts. Nothing here executes anything
the agent supplied, and nothing here reaches the game.

Input is UNTRUSTED and may be any shape at all — a bare integer, a string, None, a dict
where a list was expected. Everything malformed costs the agent its action and never the
episode, which is why nothing in this file raises on bad input.

The judgement is deliberately asymmetric, and the asymmetry is the interesting part:

    a number out of range   is repaired  — "dig 10000 tiles" means "dig a lot", and
                                           clamping keeps the intent while dropping only
                                           the exaggeration
    an unknown enum         is rejected  — a workshop type that does not exist cannot be
                                           repaired without inventing what was meant
    a verb we have declared
    but not yet wired       is rejected  — with the tranche that will deliver it, so the
                                           refusal is information rather than silence

Every refusal carries a reason, and the reasons are returned rather than logged and
forgotten: a controller that asks for something impossible should be able to find out
why. That matters more here than in most gates, because the thing on the other side of
it is a model that is supposed to learn the game.
"""

from __future__ import annotations

import re

from .library import (BUILDING_KEYS, FURNACE_KEYS, STOCKPILE_KEYS,
                      TEMPLATES_BY_NAME, cluster as pick_cluster,
                      start_offset)
from .catalog import BY_NAME, CATALOG, LIVE
from .schema import Decision, Verb

TRUE = {"1", "true", "yes", "on", "y", "t"}
FALSE = {"0", "false", "no", "off", "n", "f"}


def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in TRUE:
            return True
        if s in FALSE:
            return False
    return None


def _as_int(v) -> int | None:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(float(v.strip()))
        except ValueError:
            return None
    return None


def _bind(verb: Verb, raw) -> tuple[dict, list[str]]:
    """Match supplied arguments to declared ones, positionally or by name.

    A model writes both {"args": [10]} and {"args": {"amount": 10}}, and the difference
    is not meaningful, so both are accepted. Unknown keys are reported rather than
    ignored — a typo in an argument name is exactly the kind of thing that otherwise
    looks like it worked.
    """
    notes: list[str] = []
    if raw is None:
        raw = []
    if isinstance(raw, (str, int, float, bool)):
        raw = [raw]
    supplied: dict = {}
    if isinstance(raw, dict):
        known = {a.name for a in verb.args}
        for k, v in raw.items():
            key = str(k)
            if key in known:
                supplied[key] = v
            else:
                notes.append(f"unknown argument {key!r}")
    elif isinstance(raw, (list, tuple)):
        for i, v in enumerate(raw):
            if i < len(verb.args):
                supplied[verb.args[i].name] = v
            else:
                notes.append(f"ignored extra argument #{i + 1}")
    else:
        notes.append(f"arguments were {type(raw).__name__}, expected a list or object")
    return supplied, notes


def judge(intent) -> Decision:
    """Judge one action intent against the catalog."""
    if not isinstance(intent, dict):
        return Decision(False, reason=f"intent was {type(intent).__name__}, not an object")

    name = intent.get("verb") or intent.get("command") or intent.get("name")
    if not isinstance(name, str):
        return Decision(False, reason="no verb")
    name = name.strip()

    verb = BY_NAME.get(name)
    if verb is None:
        return Decision(False, verb=name, reason=f"{name!r} is not an action")
    if verb.status != "live":
        return Decision(False, verb=name,
                        reason=f"{name!r} is planned for tranche {verb.tranche}, "
                               f"not wired yet")

    supplied, notes = _bind(verb, intent.get("args"))
    out: list = []
    for a in verb.args:
        if a.name not in supplied:
            if a.required:
                return Decision(False, verb=name,
                                reason=f"{name!r} needs {a.name!r} ({a.doc})")
            out.append(a.default if a.default is not None else "")
            continue
        raw = supplied[a.name]

        if a.kind == "bool":
            b = _as_bool(raw)
            if b is None:
                return Decision(False, verb=name,
                                reason=f"{a.name!r} should be true or false, got {raw!r}")
            out.append(b)

        elif a.kind == "int":
            n = _as_int(raw)
            if n is None:
                return Decision(False, verb=name,
                                reason=f"{a.name!r} should be a number, got {raw!r}")
            if a.lo is not None and n < a.lo:
                notes.append(f"{a.name} {n} raised to {a.lo}")
                n = a.lo
            if a.hi is not None and n > a.hi:
                notes.append(f"{a.name} {n} lowered to {a.hi}")
                n = a.hi
            out.append(n)

        elif a.kind == "enum":
            s = str(raw).strip()
            match = next((c for c in (a.choices or ()) if c.lower() == s.lower()), None)
            if match is None:
                return Decision(False, verb=name,
                                reason=f"{a.name!r} must be one of "
                                       f"{', '.join(a.choices or ())}; got {s!r}")
            if match != s:
                notes.append(f"{a.name} {s!r} read as {match!r}")
            out.append(match)

        else:                                    # str — the game validates the specifics
            s = str(raw).strip()
            if not s:
                return Decision(False, verb=name, reason=f"{a.name!r} was empty")
            out.append(s)

    if name == "build_workshop_cluster":
        expanded = _expand_cluster(str(out[0]), int(out[1] or 1))
        if expanded is None:
            return Decision(False, verb=name,
                            reason=f"no {out[0]!r} cluster at scale {out[1]}")
        out = expanded

    if name == "apply_template":
        # The library is python's. Expanding here means the DFHack side never holds a
        # second copy of the template table that could drift from this one — it receives
        # a quickfort name, a measured extent and the blueprint's own anchor, and does
        # what it is told.
        out = _expand_template(str(out[0]), str(out[1] or "dig"))

    if name == "build_room":
        request_id = str(out[3] or "default")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", request_id):
            return Decision(False, verb=name,
                            reason="request_id must be 1..64 safe identifier characters")
        expanded = _expand_room(str(out[0]), str(out[1] or "auto"),
                                str(out[2] or "role"), request_id)
        if expanded is None:
            return Decision(False, verb=name,
                            reason=f"{out[0]!r} is not a generated room template")
        out = expanded

    return Decision(True, verb=name, args=out, repairs=notes)


def _expand_cluster(name: str, scale: int):
    """Resolve a cluster name into the membership the DFHack side will build.

    Sent as `W:Carpenters,F:Smelter` rather than as quickfort keys, so the Lua holds no
    second copy of the key table to drift from the library's — the same reason
    apply_template is expanded here.
    """
    c = pick_cluster(name, scale)
    if c is None:
        return None
    members = ",".join(
        ("F:" if k in FURNACE_KEYS else "W:") + BUILDING_KEYS[k] for k in c.workshops)
    piles = ",".join(STOCKPILE_KEYS[k] for k in c.stockpiles)
    w, h = c.footprint
    return [c.name, members, piles, w, h]


def _expand_template(name: str, stage: str = "dig") -> list:
    """Expand a template name into what the DFHack side needs.

    The FURNITURE list travels with it. The owner's point: a build request has to raise
    the work orders it implies by itself, because DF will not let you place a bed that
    does not exist — and a design that names five pieces the fort has never made is a
    request nobody acted on.
    """
    t = TEMPLATES_BY_NAME[name]
    w, h = t.footprint
    sx, sy = start_offset(t)
    label, mode = t.label, t.label_mode
    if stage == "rooms":
        # the second pass: the zone and the furniture, once the digging has finished
        label, mode = "rooms", "build"
    return [t.qf_name, w, h, t.levels, sx, sy, label, mode, _furniture_of(t)]


def _furniture_of(t) -> str:
    """`b:1,c:1,t:1,d:1` — what the design puts in the room, from the archive that made it.

    Shipped DFHack blueprints carry no piece list of ours, so they send nothing and the
    dispatcher orders nothing for them.

    THE DOORWAY COUNTS. It is not in `pieces` — it lives in `cells` as `+`, because
    validate treats it as part of the room's shape rather than as furniture — but the
    build section emits a `d` for it and DF will not hang a door that does not exist.
    Measured: the office stamped three planned buildings and ordered two, so the door sat
    at stage 0/1 forever with nothing on the manager's list to ever satisfy it.
    """
    if t.shipped:
        return ""
    try:
        from ..design.archive import load
    except ImportError:
        return ""
    entry = next((e for e in load() if e.name == t.name), None)
    if entry is None:
        return ""
    counts: dict[str, int] = {}
    for _, _, key in entry.pieces:
        counts[key] = counts.get(key, 0) + 1
    doors = sum(row.count("+") for row in entry.cells)
    if doors:
        counts["d"] = counts.get("d", 0) + doors
    return ",".join(f"{k}:{n}" for k, n in sorted(counts.items()))


def _expand_room(name: str, terrain: str = "auto", owner: str = "role",
                 request_id: str = "default") -> list | None:
    """Everything the trusted side needs to resume and verify one room request."""
    t = TEMPLATES_BY_NAME[name]
    if t.shipped:
        return None
    try:
        from ..design.archive import load
    except ImportError:
        return None
    entry = next((e for e in load() if e.name == name), None)
    if entry is None:
        return None
    d = entry.to_design()
    w, h = t.footprint
    sx, sy = start_offset(t)
    zone = d.zone_cells
    xs = [x for x, _ in zone]
    ys = [y for _, y in zone]
    zx, zy = min(xs), min(ys)
    zw, zh = max(xs) - zx + 1, max(ys) - zy + 1
    dig = sum(ch in ".se+" for row in d.cells for ch in row)
    smooth = sum(ch in "se" for row in d.cells for ch in row)
    walls = sum(ch == "#" for row in d.cells for ch in row)
    floors = dig
    doors = [(x, y) for y, row in enumerate(d.cells)
             for x, ch in enumerate(row) if ch == "+"]
    if len(doors) != 1:
        return None
    door_x, door_y = doors[0]
    surface_name = t.qf_name[:-4] + "-surface.csv"
    return [
        t.qf_name, surface_name, w, h, sx, sy, entry.kind, entry.position,
        _furniture_of(t), dig, smooth, walls, floors, zx, zy, zw, zh,
        door_x, door_y, entry.demand, terrain, owner, request_id,
    ]


def sanitize(raw_actions) -> tuple[list[dict], list[str]]:
    """Judge a batch. Returns the dispatchable actions and the refusals, in order.

    Shape of an accepted action is `{"verb": str, "args": list}` — unchanged from the
    original gate, so the DFHack dispatcher does not care that any of this happened.
    """
    if isinstance(raw_actions, dict):
        raw_actions = [raw_actions]
    if not isinstance(raw_actions, (list, tuple)):
        return [], [f"actions were {type(raw_actions).__name__}, expected a list"]

    clean, said = [], []
    for i, a in enumerate(raw_actions):
        d = judge(a)
        if d.ok:
            clean.append({"verb": d.verb, "args": d.args})
            said.extend(f"#{i + 1} {d.verb}: {r}" for r in d.repairs)
        else:
            said.append(f"#{i + 1} refused: {d.reason}")
    return clean, said


def available_actions(include_planned: bool = False) -> list[dict]:
    """The action schema handed to the controller.

    A model that is shown only verb NAMES has to guess argument order and units, and
    guesses wrong in ways that look like bad play rather than a bad interface. Shipping
    the schema costs a few hundred bytes of the observation and removes that whole class
    of failure.
    """
    src = CATALOG if include_planned else LIVE
    out = [v.describe() for v in src]

    # Emit each distinct choice list ONCE.
    #
    # The schema rides in every controller prompt, so a duplicated vocabulary is a bill
    # paid on every round forever. ORDERABLE_JOBS alone was shipping twice, once for
    # `add_workorder` and once for `add_workorder_conditional`. A repeat now says where
    # the list already is instead of repeating it — which loses nothing, because the
    # GATE validates against the catalog and `choices` on the wire is purely there to
    # tell the model what is legal.
    seen: dict[tuple, str] = {}
    for verb in out:
        for arg in verb["args"]:
            choices = arg.get("choices")
            if not choices:
                continue
            key = tuple(choices)
            where = f"{verb['verb']}.{arg['name']}"
            if key in seen:
                del arg["choices"]
                arg["same_as"] = seen[key]
            else:
                seen[key] = where
    return out


def roadmap() -> list[dict]:
    """Declared-but-unwired verbs, by tranche — the gap between the agent and a player."""
    out = [{"verb": v.name, "tranche": v.tranche, "category": v.category,
            "doc": v.doc, "guide": v.guide}
           for v in CATALOG if v.status != "live"]
    out.sort(key=lambda d: (d["tranche"], d["category"], d["verb"]))
    return out
