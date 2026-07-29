"""Map-track capture driver — the visual layer of a recording.

Drives `bonsai-map-capture.lua`, which writes one JSON snapshot per call to a scratch
file and keeps the previous tile buffer in a Lua global (globals survive between
separate dfhack-run RPC calls — verified live). This module folds those snapshots into
the episode recording so a replay is ONE self-contained file.

Recorded for only 1 of K runs: it is the expensive track, and the owner explicitly
accepted seeing one concrete run rather than paying for all K.

Measured live 2026-07-29 on the pinned fort:
    keyframe   36-43 ms   ~55 KB   (25600 tiles, RLE'd to ~7200 runs)
    delta      28-38 ms   ~2.6 KB  (3-5 tiles actually changed over 1200 ticks)
    gzip       ~6:1
So a 24-round episode with a full map track is ~45 KB and under 1 s of capture — the
delta mechanism is what makes per-round sampling affordable at all.
"""

from __future__ import annotations

import json
import os

CAPTURE_FILE = "/srv/df-bonsai/current/map_capture.jsonl"
ARGS_FILE = "/srv/df-bonsai/current/map_capture_args.txt"

# The Lua side falls back to a keyframe on its own whenever the sticky bbox grows, so
# this is only a belt-and-braces resync for long episodes.
DEFAULT_KEYFRAME_EVERY = 8


class MapRecorder:
    """Captures fort geometry + entities. One instance per recorded episode."""

    def __init__(self, session, *, capture_file: str = CAPTURE_FILE,
                 args_file: str = ARGS_FILE,
                 keyframe_every: int = DEFAULT_KEYFRAME_EVERY,
                 timeout: int = 60, max_bytes: int = 8_000_000):
        self.session = session
        self.capture_file = capture_file
        self.args_file = args_file
        self.keyframe_every = max(1, keyframe_every)
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.n = 0
        self.bytes_written = 0
        self.truncated = False
        self.errors: list[str] = []
        self._offset = 0
        for p in (self.capture_file, self.args_file):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    def snapshot(self, tick: int, *, keyframe: bool = False) -> dict | None:
        """Capture one snapshot. Returns the parsed event, or None if nothing usable.

        Raises nothing the recorder cannot absorb — EpisodeRecorder catches, but a
        silent None here keeps a bad map track from polluting the decision track.
        """
        if self.truncated:
            return None
        want_kf = keyframe or (self.n % self.keyframe_every == 0)
        try:
            with open(self.args_file, "w") as f:
                f.write(f"{'kf' if want_kf else 'd'}\n{self.capture_file}\n")
            out = self.session.run("bonsai-map-capture", timeout=self.timeout)
        except Exception as e:                       # noqa: BLE001
            self.errors.append(f"rpc: {type(e).__name__}: {e}"[:160])
            return None
        if "MAPCAP ok=1" not in out:
            self.errors.append(f"capture refused: {out.strip()[-120:]}")
            return None

        line = self._read_new_line()
        if line is None:
            return None
        self.n += 1
        self.bytes_written += len(line)
        # A recording is meant to be looked at, not to fill a disk. Stop the map track
        # (and only the map track) if a pathological fort blows the budget.
        if self.bytes_written > self.max_bytes:
            self.truncated = True
            self.errors.append(f"map track stopped at {self.bytes_written} bytes "
                               f"(cap {self.max_bytes}) after {self.n} snapshots")
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            self.errors.append(f"unparsable snapshot: {e}"[:160])
            return None

    def _read_new_line(self) -> str | None:
        """Read only what this call appended (the file accumulates across the episode)."""
        try:
            with open(self.capture_file, "r", encoding="utf-8") as f:
                f.seek(self._offset)
                chunk = f.read()
                self._offset = f.tell()
        except FileNotFoundError:
            self.errors.append("capture wrote no line (file absent)")
            return None
        except OSError as e:
            self.errors.append(f"read: {e}"[:160])
            return None
        lines = [l for l in chunk.splitlines() if l.strip()]
        if not lines:
            self.errors.append("capture wrote no line")
            return None
        return lines[-1]

    def stats(self) -> dict:
        return {"snapshots": self.n, "bytes": self.bytes_written,
                "truncated": self.truncated, "errors": self.errors[:5]}

    def close(self) -> None:
        for p in (self.capture_file, self.args_file):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
