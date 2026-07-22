"""Public API for deterministic faction morale queries.

This module wraps the existing ``bridge.faction_probe.probe_faction_morale``
function and provides a simple Python interface that returns a dictionary
mapping faction IDs to integer morale values. The implementation mirrors the
pattern used by other public probes and respects the coding‑graph contract.
"""

from typing import Dict, Optional
from .faction_probe import probe_faction_morale


def get_faction_morale(timeout: int = 20) -> Optional[Dict[int, int]]:
    """Query the live DFHack process for current faction morale.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary ``{faction_id: morale}`` on success, or ``None`` if the
        probe fails or the DF runtime is not available.
    """
    return probe_faction_morale(timeout=timeout)

# deterministic edit marker
