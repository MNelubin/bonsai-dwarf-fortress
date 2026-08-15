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

from .library import TEMPLATES_BY_NAME, start_offset
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

    if name == "apply_template":
        # The library is python's. Expanding here means the DFHack side never holds a
        # second copy of the template table that could drift from this one — it receives
        # a quickfort name, a measured extent and the blueprint's own anchor, and does
        # what it is told.
        out = _expand_template(str(out[0]))

    return Decision(True, verb=name, args=out, repairs=notes)


def _expand_template(name: str) -> list:
    t = TEMPLATES_BY_NAME[name]
    w, h = t.footprint
    sx, sy = start_offset(t)
    return [t.qf_name, w, h, t.levels, sx, sy, t.label, t.label_mode]


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
    return [v.describe() for v in src]


def roadmap() -> list[dict]:
    """Declared-but-unwired verbs, by tranche — the gap between the agent and a player."""
    out = [{"verb": v.name, "tranche": v.tranche, "category": v.category,
            "doc": v.doc, "guide": v.guide}
           for v in CATALOG if v.status != "live"]
    out.sort(key=lambda d: (d["tranche"], d["category"], d["verb"]))
    return out
