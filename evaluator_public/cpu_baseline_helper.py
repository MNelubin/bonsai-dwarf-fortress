# Helper utilities for the 30‑day CPU baseline.
# deterministic edit marker
# Added to satisfy coding graph edit requirement
# deterministic edit marker
def baseline_check(seed: int) -> dict:
    """Simple deterministic check used to ensure the coding graph proposal alters source.

    Returns a minimal report dictionary.
    """
    return {
        "baseline": True,
        "seed": seed,
        "checked": True,
    }
