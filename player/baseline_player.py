

from typing import Any, Dict

class BaselinePlayer:
    """Simple rules‑based player for 30‑day CPU baseline evaluation."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.metrics: Dict[str, Any] = {}

    async def run(self) -> None:
        """Simulate a 30‑day run and record worst‑run metrics.

        This stub performs no actual gameplay; it only demonstrates the
        expected public interface so that downstream evaluation code can
        import and call it. Concrete behavior would be added in future
        coding cycles.
        """
        for _day in range(1, 31):
            # Placeholder for per‑day logic
            pass
        # Capture failure taxonomy metadata (empty for this stub)
        self.metrics["seed"] = self.seed
        self.metrics["duration_days"] = 30
        self.metrics["failures"] = []

    def report(self) -> Dict[str, Any]:
        """Return collected metrics as a JSON‑serialisable dict."""
        return self.metrics
