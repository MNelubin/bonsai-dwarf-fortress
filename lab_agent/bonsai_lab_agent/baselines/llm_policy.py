"""A controller that asks a local language model what to do.

The smallest possible agent: no autonomy loop, no code editing, no memory beyond what
the driver hands it each round. One observation in, one list of actions out, through the
same contract every tier uses -- the action schema the driver ships, the dependency view,
the threat channel, and the receipt for last round's actions. If the contract cannot
carry a competent game to a model, this is where it shows, and it shows before anything
autonomous is built on top of it.

The model runs on the lab's own Ollama. No hosted provider is involved.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

OLLAMA_URL = os.environ.get("BONSAI_OLLAMA_URL", "http://100.96.0.4:11434").rstrip("/")
MODEL = os.environ.get("BONSAI_LLM_MODEL", "qwen3.8:latest")
ROUND_TIMEOUT_S = float(os.environ.get("BONSAI_LLM_TIMEOUT", "120"))
LOG = os.environ.get("BONSAI_LLM_LOG")            # append raw exchanges here, if set

ADVANCE = [{"command": "advance"}]

SYSTEM = """You are managing a Dwarf Fortress fort through a fixed set of commands.
Each round you receive the fort's state and the receipt for your previous commands, and
you reply with the commands for this round as JSON: {"actions": [{"command": NAME,
"args": [...]}, ...]}. Use only the commands listed under action_schema, with arguments
in the order and types given there. An empty list means do nothing this round.

What the score rewards: everyone alive at the end, and a fort that has dug more rock,
raised more finished buildings and completed more work orders than when you started.
What you should know: a fresh embark's wood is locked in the wagon and cannot be built
with -- fell trees first; digging designations beyond what your miners can reach before
your next turn slow them down rather than speed them up; a labour switched on for the
whole fort pulls every dwarf onto it. Read previous_action_feedback: REFUSED means nothing
happened and says why, NOTE means it happened with a caveat."""

_schema_cache: list | None = None


def _compact(obs: dict) -> dict:
    """The observation as the model sees it: everything decision-relevant, nothing huge."""
    global _schema_cache
    if obs.get("action_schema"):
        _schema_cache = obs["action_schema"]
    keep = ("round", "rounds_total", "ticks_remaining", "cohort_alive", "cohort_size",
            "dug_tiles", "buildings", "workorders_done", "food_count", "drink_count",
            "hostiles", "hostiles_on_map", "injured", "danger_events", "under_threat",
            "warnings", "cancellations", "cancel_reasons", "dependencies")
    out = {k: obs.get(k) for k in keep if k in obs}
    fb = obs.get("previous_action_feedback")
    if fb:
        out["previous_action_feedback"] = {
            "requested": fb.get("requested"),
            "gate_messages": fb.get("gate_messages"),
            "dfhack": str(fb.get("dfhack") or "")[:1200],
        }
    out["action_schema"] = _schema_cache
    return out


def _ask(payload: dict) -> str:
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        # qwen3 reasons before it answers unless told not to, and on a full fort
        # observation that reasoning ran past a two-minute round with no JSON at the
        # end of it. Measured on the lab's Ollama: a trivial ask takes 1.2s without
        # thinking and 2.4s with; the first round of the first episode took 120s and
        # timed out. A controller gets one round's worth of time, not a monologue.
        "think": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": 16384},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"), default=str)},
        ],
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=ROUND_TIMEOUT_S) as r:
        return json.loads(r.read())["message"]["content"]


def _parse(text: str) -> list[dict]:
    """Whatever the model wrote, or nothing. Never raise into the driver."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    acts = data.get("actions") if isinstance(data, dict) else data
    if not isinstance(acts, list):
        return []
    clean = []
    for a in acts:
        if isinstance(a, dict) and isinstance(a.get("command"), str):
            args = a.get("args", [])
            clean.append({"command": a["command"], "args": list(args) if isinstance(args, (list, tuple)) else [args]})
    return clean


def llm_policy(obs: dict) -> list[dict]:
    payload = _compact(obs)
    t0 = time.time()
    try:
        raw = _ask(payload)
        acts = _parse(raw)
        err = None
    except Exception as exc:                       # a slow or dead model costs this round only
        raw, acts, err = "", [], f"{type(exc).__name__}: {exc}"
    if LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"round": obs.get("round"), "seconds": round(time.time() - t0, 1),
                                    "error": err, "reply": raw[:2000], "actions": acts},
                                   default=str) + "\n")
        except OSError:
            pass
    return acts or ADVANCE
