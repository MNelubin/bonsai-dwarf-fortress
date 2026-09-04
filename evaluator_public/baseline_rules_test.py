"""
Deterministic public test for bridge.baseline_rules.collect_baseline.

This test imports the baseline_rules module and verifies that the public
collect_baseline function returns a dict containing the required contract keys
and correctly handles missing cpu_time attributes.
"""
import unittest
from bridge.baseline_rules import collect_baseline


class BaselineRulesPublicTest(unittest.TestCase):
    """Validate the public API of bridge.baseline_rules.collect_baseline."""
    def test_required_keys(self):
        """The result must contain all required keys.

        A dummy state without cpu_time is used; the function should fall back
        to default behavior (0.0 seconds, worst_cpu=False).
        """
        class DummyState:
            pass
        result = collect_baseline(seed=42, game_state=DummyState())
        self.assertIsInstance(result, dict)
        required = {"seed", "cpu_seconds", "worst_cpu", "failure_taxonomy"}
        missing = required - result.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_missing_attribute_fallback(self):
        """When cpu_time is missing the function should not error.

        The fallback behavior is cpu_seconds=0.0 and worst_cpu=False.
        """
        class NoCpuState:
            pass
        result = collect_baseline(seed=7, game_state=NoCpuState())
        self.assertEqual(result["cpu_seconds"], 0.0)
        self.assertFalse(result["worst_cpu"])
        self.assertEqual(result["failure_taxonomy"], [])


if __name__ == "__main__":
    unittest.main()
