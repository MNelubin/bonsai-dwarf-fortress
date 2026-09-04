import unittest
from evaluator_public.implementation import run_simulation

class Test30DayCpuBaseline(unittest.TestCase):
    def test_baseline(self):
        result = run_simulation(seed=12345)
        self.assertIsNotNone(result)
        self.assertIn('cpu_time', result)
        self.assertIn('worst_metric', result)

if __name__ == "__main__":
    unittest.main()
