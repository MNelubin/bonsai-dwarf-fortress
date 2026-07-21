import unittest
import subprocess
import os
import json

class CpuBaselineTest(unittest.TestCase):
    """Test that a rules‑based player produces consistent CPU usage metrics over 30 days across multiple seeds."""
    SEEDS = ["seed1","seed2","seed3"]
    DURATION = 30  # days

    def _run_30_day_simulation(self, seed):
        """Run a 30‑day simulation for the given seed and capture CPU time.

        The bridge/launcher entry point is assumed to be `python -m bridge.run`.
        """
        cmd = [
            "python3",
            "-m",
            "bridge.run",
            f"--seed={seed}",
            f"--duration={self.DURATION}",
            "--cpu-metrics",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            timeout=3600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Simulation for seed {seed} failed: {result.stderr}\nstdout: {result.stdout}"
            )
        # Expect JSON output: {"seed":..., "cpu_time_seconds":...}
        data = json.loads(result.stdout)
        self.assertIn("cpu_time_seconds", data)
        return data["cpu_time_seconds"]

    def test_consistent_cpu_baseline(self):
        """Collect CPU usage for each seed and assert they fall within a reasonable range."""
        times = []
        for seed in self.SEEDS:
            times.append(self._run_30_day_simulation(seed))
        min_time = min(times)
        max_time = max(times)
        mean_time = sum(times) / len(times)

        # Allow up to 20 % variance between min and max – this is a conservative baseline.
        self.assertLess((max_time - min_time) / mean_time, 0.20)

        # Record worst‑run metrics for downstream analysis.
        with open(os.path.join(os.path.dirname(__file__), "baseline_report.json"), "w") as f:
            json.dump({
                "seed": self.SEEDS[times.index(max_time)],
                "worst_cpu_seconds": max_time,
                "best_cpu_seconds": min_time,
                "average_cpu_seconds": mean_time,
            }, f, indent=2)

if __name__ == "__main__":
    unittest.main()
