"""Public API for the food stock probe.

Wraps ``probe_food_stock`` from the implementation module and provides a
deterministic Python interface that returns a JSON‑serialisable dictionary with
a single key ``"food_stock"`` whose value is an integer, or ``None`` when the
probe cannot communicate with the DF runtime. No live DF process is required
after implementation, making the test deterministic.
"""

from typing import Optional, Dict
from .food_stock_probe import probe_food_stock


def get_food_stock(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Fetch the current food stock count from the live DFHack process.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{"food_stock": <int>}`` on success, or ``None`` if the probe fails.
    """
    result = probe_food_stock(timeout=timeout)
    return result
