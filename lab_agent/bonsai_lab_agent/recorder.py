"""Episode recorder — the replay/audit file.

DF is not bit-reproducible (proven: render<->logic thread concurrency), so an
input-log replay in the Doom/StarCraft sense is impossible: re-simulating the same
inputs yields a DIFFERENT game. This records what ACTUALLY HAPPENED instead — an
observation recording, not an input recording.

That is a feature, not a consolation. The file is written by TRUSTED code from DFHack
ground truth, so it doubles as audit evidence: the recorded observations are the same
ones the score was computed from, and the decision track shows exactly which agent
intents were allowed and which the anti-forgery gate dropped.

Layers, by cost (measured live 2026-07-29):
  * decision track  one event per controller round      ~free
  * metric track    the scored observables per round    ~free - the stepped driver
                    already observes every round, so this layer costs NOTHING extra
  * map track       tiles/units/items for the viewer    ~94ms a snapshot; separate
                    module, recorded for only 1 of K runs

Format: gzipped JSONL, one event per line, `zcat file.rec.jsonl.gz | head`. No schema
registry, no binary framing — the same dependency-free instinct as the tab-separated
action file. Deliberately debuggable.

NEVER RAISES into an episode. The stepped driver swallows recorder exceptions too;
this is the second layer of that belt.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from typing import Any

REC_DIR = os.environ.get("BONSAI_REC_DIR", "/srv/df-bonsai/recordings")
FORMAT_VERSION = 1


def _jsonable(v: Any) -> Any:
    """Best-effort shrink to JSON. Untrusted controllers can return exotic objects."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in list(v.items())[:64]}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in list(v)[:64]]
    return str(v)[:500]


class EpisodeRecorder:
    """Writes one .rec.jsonl.gz for one episode.

    Hook names match what stepped_episode calls: on_start / on_round / on_end / close.
    """

    def __init__(self, path: str, *, meta: dict | None = None,
                 map_recorder=None, clock=time.time):
        self.path = path
        self.meta = dict(meta or {})
        self.map_recorder = map_recorder
        self._clock = clock
        self._fh = None
        self._t_open = clock()
        self.events = 0
        self.errors: list[str] = []
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._fh = gzip.open(path, "wt", encoding="utf-8", compresslevel=6)

    # ------------------------------------------------------------------ writing
    def _write(self, obj: dict) -> None:
        if self._fh is None:
            return
        try:
            self._fh.write(json.dumps(obj, separators=(",", ":"), default=str) + "\n")
            self.events += 1
        except Exception as e:                       # noqa: BLE001
            self.errors.append(f"{type(e).__name__}: {e}"[:200])

    # ------------------------------------------------------------------ hooks
    def on_start(self, t0_raw: dict, t0_obs, horizon_ticks: int, rounds: int) -> None:
        self._write({
            "v": FORMAT_VERSION, "kind": "meta",
            "horizon_ticks": horizon_ticks, "rounds": rounds,
            "t0_tick": t0_obs.abs_tick, "cohort_size": t0_obs.cohort_size,
            "t0_raw": _jsonable(t0_raw),
            **self.meta,
        })
        self._write({"kind": "stat", "i": -1, "phase": "t0", **_obs_fields(t0_obs)})
        self._snapshot_map(-1, t0_obs.abs_tick, keyframe=True)

    def on_round(self, i: int, cobs: dict, raw_actions, kept, dispatched,
                 applied: str, error: str | None, decide_ms: int, post_raw: dict) -> None:
        """One controller round: what it saw, what it asked for, what we allowed."""
        from bonsai_lab_agent.actions import sanitize
        from bonsai_lab_agent.stepped_episode import dependency_state

        _, gate_messages = sanitize(raw_actions)
        self._write({
            "kind": "round", "i": i,
            "tick": cobs.get("cur_tick"), "ticks_remaining": cobs.get("ticks_remaining"),
            "decide_ms": decide_ms,
            "dependencies": _jsonable(cobs.get("dependencies")),
            "post_dependencies": _jsonable(dependency_state(post_raw)),
            "intents": _jsonable(raw_actions),
            "kept": _jsonable(kept),
            "dispatched": [a.get("verb") for a in dispatched],
            "dropped": _dropped(raw_actions),
            "gate_messages": [message[:240] for message in gate_messages[:16]],
            "applied": (applied or "")[:400],
            "controller_error": error,
        })

    def on_post_round(self, i: int, tick: int, obs) -> None:
        """Metric sample after a round's advance. Free — the driver already observed."""
        self._write({"kind": "stat", "i": i, "phase": "post", **_obs_fields(obs)})
        self._snapshot_map(i, tick, keyframe=False)

    def on_end(self, h_obs) -> None:
        self._write({"kind": "stat", "i": 9999, "phase": "horizon", **_obs_fields(h_obs)})
        self._write({"kind": "end", "events": self.events + 1,
                     "wall_s": round(self._clock() - self._t_open, 2),
                     "recorder_errors": self.errors[:5]})

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.close()
            except Exception:                        # noqa: BLE001
                pass
        if self.map_recorder is not None:
            try:
                self.map_recorder.close()
            except Exception:                        # noqa: BLE001
                pass

    # ------------------------------------------------------------------ map track
    def _snapshot_map(self, i: int, tick: int, *, keyframe: bool) -> None:
        if self.map_recorder is None:
            return
        try:
            ev = self.map_recorder.snapshot(tick, keyframe=keyframe)
        except Exception as e:                       # noqa: BLE001
            self.errors.append(f"map {type(e).__name__}: {e}"[:200])
            return
        if not ev:
            return
        # The snapshot carries its OWN "kind" ("kf"/"d") — splatting it blindly used to
        # overwrite "kind":"map" and made map events unfindable. Record what we actually
        # GOT rather than what we asked for: the capture script promotes a delta to a
        # keyframe on its own whenever the fort's bounding box grows, and a viewer that
        # trusted the request would try to apply a keyframe as a diff.
        actual_kf = (ev["kind"] == "kf") if "kind" in ev else bool(ev.get("keyframe", keyframe))
        payload = {k: v for k, v in ev.items() if k not in ("kind", "keyframe")}
        self._write({"kind": "map", "i": i, "tick": tick,
                     "keyframe": actual_kf, "requested_keyframe": keyframe, **payload})

    # ------------------------------------------------------------------ size
    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


def _dropped(raw_actions) -> list[dict]:
    """Which of the agent's intents the anti-forgery gate refused, and why.

    Asks the gate itself about each intent rather than re-deriving the rule here — a
    recorder that disagreed with the real gate would be worse than no record, since this
    file is meant to be audit evidence. (It first did key-matching against the kept set,
    and mislabelled a bare `advance` as rejected because sanitize normalises a missing
    `args` to [] while the raw intent has none.)

    The reason is the gate's own sentence, not a category: "'plant_crop' is not an
    action" and "add_workorder needs 'job'" are different problems and a replay that
    called both `not_allow_listed` hid which one the agent kept making.
    """
    from bonsai_lab_agent.actions import judge

    if isinstance(raw_actions, dict):
        raw_actions = [raw_actions]
    if not isinstance(raw_actions, (list, tuple)):
        return [{"reason": "not_a_list", "raw": _jsonable(raw_actions)}]
    out = []
    for a in raw_actions:
        d = judge(a)
        if not d.ok:
            out.append({"reason": d.reason,
                        "verb": _jsonable(d.verb or (isinstance(a, dict) and
                                                     (a.get("command") or a.get("name")))),
                        "raw": _jsonable(a)})
    return out


def _obs_fields(o) -> dict:
    return {
        "tick": o.abs_tick,
        "alive": o.cohort_alive, "cohort": o.cohort_size,
        "hunger": o.hunger_sum, "thirst": o.thirst_sum, "stress_danger": o.stress_danger,
        "food": o.food_count, "drink": o.drink_count,
        "buildings": o.buildings, "dug": o.dug_tiles, "workorders": o.workorders_done,
    }


def read_recording(path: str) -> list[dict]:
    """Read a .rec.jsonl.gz back into events. Tolerates a truncated tail — an episode
    killed by the watchdog still leaves a readable partial recording, which is exactly
    when you most want to look at it."""
    out: list[dict] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break                            # truncated tail; keep what we have
    except (OSError, EOFError):
        pass
    return out


def recording_path(episode_id: str, rec_dir: str = REC_DIR) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in episode_id)[:120]
    return os.path.join(rec_dir, f"{safe}.rec.jsonl.gz")
