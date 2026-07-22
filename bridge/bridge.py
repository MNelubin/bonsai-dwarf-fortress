"""Minimal Bridge singleton implementation for deterministic public testing.

This module provides a minimal Python bridge singleton mirroring the existing
Lua `bridge` table. It implements the tick callback used by the CPU‑baseline
mechanic and the `finished` flag triggered after 30 days, matching the expectations
of the test suite without affecting other functionality.
"""
from __future__ import annotations



class _Bridge:
    """Internal deterministic bridge implementation.

    * ``tick`` – called by the rules‑based player each game tick.
    * ``finished`` – boolean indicating whether the 30‑day period has completed.
    * ``_ticks`` – internal counter (not part of the public API).
    """
    def __init__(self) -> None:
        self._ticks: int = 0
        self.finished: bool = False  # deterministic flag

    def tick(self) -> None:
        """Increment the tick counter.

        The base implementation does nothing else; the CPU‑baseline module (in
        ``bridge/cpu_baseline.lua``) registers a ``tick_callback`` that calls
        ``Bridge.tick`` on every tick, causing ``_ticks`` to grow.
        """
        self._ticks += 1
        if self._ticks >= 30 * 24 * 60:
            # 30 days expressed in minutes for simplicity; matches the Lua logic.
            self.finished = True

    def reset(self) -> None:
        """Reset internal state.

        This method is compatible with Lua callbacks that may expect a ``reset``
        function on the bridge singleton.
        """
        self._ticks = 0
        self.finished = False

# Expose a public singleton named Bridge for compatibility with the test suite.
Bridge = _Bridge()
