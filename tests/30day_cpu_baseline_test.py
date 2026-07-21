import unittest

class Test30DayCPUBaseline(unittest.TestCase):
    def test_baseline_exists(self):
        """Ensure the 30‑day CPU baseline configuration is present."""
        from game_runner.load_baseline import load_baseline
        baseline = load_baseline('30day_cpu')
        self.assertIsNotNone(baseline, "30‑day CPU baseline not loaded")
        self.assertIn('cpu_metrics', baseline)

if __name__ == "__main__":
    unittest.main()
