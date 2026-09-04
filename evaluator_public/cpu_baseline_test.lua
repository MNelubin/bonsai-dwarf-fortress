-- deterministic public test for cpu_baseline in evaluator_public
local unittest = require('unittest')
local run_simulation = require('evaluator_public.implementation').run_simulation

class CpuBaselineTest(unittest.TestCase):
    SEEDS = [12345, 67890, 13579]

    def test_worst_run_is_dict(self):
        for seed in self.SEEDS:
            result = run_simulation(seed=seed)
            self.assertIsInstance(result.get('worst_run'), dict)

if __name__ == '__main__':
    unittest.main()
