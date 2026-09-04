import unittest
from evaluator_public.implementation import run_simulation

class CpuBaselineTest(unittest.TestCase):
    SEEDS = [12345, 67890, 13579]
    DURATION_DAYS = 30

    def test_cpu_and_worst_run(self):
        for seed in self.SEEDS:
            result = run_simulation(seed=seed)
            self.assertIsNotNone(result, f"Run returned None for seed {seed}")
            self.assertIn('cpu_time', result, f"cpu_time missing for seed {seed}")
            self.assertIn('cpu_usage', result, f"cpu_usage missing for seed {seed}")
            self.assertIn('worst_run', result, f"worst_run missing for seed {seed}")
            worst = result['worst_run']
            self.assertIsInstance(worst, dict)
            self.assertGreater(len(worst), 0, f"worst_run dict empty for seed {seed}")

if __name__ == '__main__':
    unittest.main()
