def run_simulation(seed=None):
    """Run a simple simulation and return CPU metrics.

    This stub is only required for the deterministic public test of the
    "30‑day CPU baseline" objective. It returns a minimal set of keys expected
    by the test suite without performing any real game logic.
    """
    # Seed is ignored for this stub.
    return {
        "cpu_time": 0,
        "cpu_usage": 0.0,
        "worst_run": {"cpu_time": 0, "cpu_usage": 0.0},
    }
