import unittest
from evaluator_public.implementation import run_simulation  # coding_graph edit

class CpuBaselineTest(unittest.TestCase):
    SEEDS = [12345, 67890, 13579]
    def test_cpu_and_worst_run(self):
        for seed in self.SEEDS:
            result = run_simulation(seed=seed)
            self.assertIsNotNone(result, f"None for seed {seed}")
            self.assertIn('cpu_time', result, f"cpu_time missing for {seed}")
            self.assertIn('cpu_usage', result, f"cpu_usage missing for {seed}")
            self.assertIn('worst_run', result, f"worst_run missing for {seed}")
            wr = result['worst_run']
            self.assertIsInstance(wr, dict)
            self.assertGreater(len(wr), 0)  # ensure worst_run dict is non‑empty

if __name__ == '__main__':
    unittest.main()
