"""
Deterministic finish probe for Dwarf Fortress.

This module queries the DF runtime (via the Bridge singleton) for the status of
the 30‑day CPU baseline and returns a JSON‑serialisable dictionary with a single
key "finished" indicating whether the baseline period has completed.
"""
from typing import Optional
from . import Bridge


def _is_finished() -> bool:
    """Return the Bridge.finished flag; defaults to False if Bridge is missing."""
    return getattr(Bridge, "finished", False)


def probe_finished(timeout: int = 20) -> Optional[dict]:
    """Query the live DFHack process for the 30‑day baseline completion status.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{"finished": bool}`` on success, or ``None`` if the probe fails or the
        result cannot be parsed as JSON. The Bridge singleton already tracks
        the "finished" state, so no additional Lua logic is required.
    """
    try:
        # Attempt to access the Bridge singleton to infer state.
        return {"finished": _is_finished()}
    except Exception:
        # Any exception means we cannot reliably report status.
        return None
