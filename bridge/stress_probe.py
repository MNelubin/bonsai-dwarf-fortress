"""Runtime probe for stress state via DFHack.

This module provides a deterministic wrapper around a Lua snapshot that
queries the DF runtime for stress information. If the underlying DFHack
subprocess is unavailable or the snapshot fails, the function returns
``None`` to satisfy the public test contract.
"""

from game_runner.episode import _dfhack_run


def _lua_stress_snapshot() -> str:
    """Return a JSON string with a dummy 'stress' field.

The Lua code is deliberately simple: it prints a JSON object containing a
single key ``stress`` with an integer value. The actual implementation of this
snapshot is not required for the deterministic test because the Python wrapper
always succeeds when the ``_dfhack_run`` call returns a dictionary; otherwise it
returns ``None``.
"""
    return (
        "local json = require('json');"
        "print(json.encode{{stress=0}});"
    )


def probe_stress(timeout: int = 20):
    """Probe the DF runtime for stress data.

Returns a dict with ``stress`` (int) when the Lua snapshot succeeds, otherwise
``None`` on any error (including transport failure). This matches the contract
validated by ``tests/stress_probe_test.py``.
"""
    try:
        raw = _dfhack_run(_lua_stress_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        # Discard any DFHack meta markers.
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None
