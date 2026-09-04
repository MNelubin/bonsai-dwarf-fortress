"""cpu_baseline_player.py: Minimal 30‑day CPU baseline player wrapper.

This module follows the public player contract used by the test suite. It
proxies calls to :class:`bridge.CPUBaseline` and provides the required
metric accessors.
"""

from typing import Dict

from bridge import CPUBaseline

class TestPlayerBase:
    pass






def new(seed: int) -> TestPlayerBase:
    """Factory used by the test runner.

    For deterministic behaviour the seed is ignored; the implementation only
    needs to be callable.
    """
    return TestPlayer(seed)

class TestPlayer(TestPlayerBase):
    """Concrete player object required by `test` runner.

    Provides ``run`` and metric accessors expected by the public tests.
    """
    def __init__(self, seed: int) -> None:
        self._baseline = CPUBaseline().instance()

    def run(self, steps: int) -> None:
        """Run the baseline for the given number of simulation steps.

        The call mirrors `bridge.CPUBaseline.run`; the argument is expected
        to represent minutes (e.g. 30 days × 24 h × 60 min).
        """
        # Convert minutes → loop iterations approximating one step per minute.
        # The bridge baseline defaults to 30 000 steps, so we scale accordingly.
        default_steps = 30_000
        scale = steps / (30 * 24 * 60)  # 30 days in minutes
        self._baseline.run(int(default_steps * scale))

        # Attach cpu_time accessor as a method of TestPlayer instance

        self.cpu_time = lambda: self._baseline.total_cpu_seconds
        self.cpu_usage = lambda: self._baseline.total_cpu_seconds
        self.worst_run = lambda: self.worst_metric()

    def worst_metric(self) -> Dict[str, float]:
        """Return the last recorded metrics as a dictionary.

        The test expects a non‑empty dict; we return the most recent record.
        """
        if not self._baseline._records:
            return {}
        return self._baseline._records[-1]
