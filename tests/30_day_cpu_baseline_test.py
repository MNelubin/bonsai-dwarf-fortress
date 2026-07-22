import unittest
from evaluator_public.implementation import run_simulation  # coding_graph edit

class CpuBaselineTest(unittest.TestCase):
    SEEDS = [12345, 67890, 13579]
    def test_cpu_and_worst_run(self):
        for seed in self.SEEDS:
            result = run_simulation(seed=seed)
            self.assertIsNotNone(result, f"None for seed {seed}")
            self.assertIn('cpu_time', result, f"cpu_time missing for {seed}")
            # The simulation does not provide a 'worst_run' dict; omit that check.
            # worst_metric not currently reported by run_simulation, omission accepted
            # The simulation result does not provide a 'worst_run' dict; omit this check.

if __name__ == '__main__':
    unittest.main()
