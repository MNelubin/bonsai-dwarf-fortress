"""Public test for bridge.baseline_rules.collect_baseline.

This file creates a tiny deterministic test to verify that the baseline_rules
function returns the required schema keys and handles missing attributes correctly.
"""
import unittest
from bridge.baseline_rules import collect_baseline


class CollectBaselinePublicTest(unittest.TestCase):
    """Validate public contract of \"collect_baseline\" function."""
    def test_required_keys_present(self):
        class Dummy:
            pass
        result = collect_baseline(seed=0, game_state=Dummy())
        self.assertIsInstance(result, dict, "Result should be a dict")
        required = {"seed", "cpu_seconds", "worst_cpu", "failure_taxonomy"}
        missing = required - result.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_missing_attribute_fallback(self):
        class Empty:
            pass
        result = collect_baseline(seed=999, game_state=Empty())
        self.assertEqual(result["cpu_seconds"], 0.0)
        self.assertFalse(result["worst_cpu"])
        self.assertListEqual(result["failure_taxonomy"], [])

    def test_non_numeric_cpu_time(self):
        class BadState:
            cpu_time = None
        result = collect_baseline(seed=123, game_state=BadState())
        self.assertEqual(result["cpu_seconds"], 0.0)
        self.assertFalse(result["worst_cpu"])
        self.assertListEqual(result["failure_taxonomy"], [])


if __name__ == "__main__":
    unittest.main()
