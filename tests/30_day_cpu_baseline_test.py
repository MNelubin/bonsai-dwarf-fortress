import unittest
from game_runner.runner import run_simulation

class CpuBaselineTest(unittest.TestCase):
    def test_baseline_metrics(self):
        # Run a single seed simulation and verify basic CPU metrics are collected.
        result = run_simulation(seed=0)
        self.assertIn("cpu_time", result)

        self.assertIn("cpu_usage", result)

        # Ensure worst‑run metrics are present.
        self.assertIn("worst_run", result)
        self.assertIsInstance(result["worst_run"], dict)

if __name__ == "__main__":
    unittest.main()
