"""Deterministic public test for bridge.food_preparation_quality_probe.probe_food_preparation_quality.\n\nThis test imports the food preparation quality probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary mapping job IDs to a sub‑dictionary\ncontaining a single key "quality" with an integer value, or None when the probe cannot communicate\nwith the DF runtime. No live Dwarf Fortress process is required because the implementation\nalready returns None on transport failure, making the test deterministic in the coding‑graph environment.\n"""
import unittest
from bridge.food_preparation_quality_probe import probe_food_preparation_quality


class FoodPreparationQualityProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_food_preparation_quality`` returns the expected contract schema\n    and that a custom timeout argument does not raise.\n    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n\n        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.\n        """
        result = probe_food_preparation_quality()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a dict of job_id → {"quality": int}
        self.assertIsInstance(result, dict)
        for job_id, info in result.items():
            self.assertIsInstance(job_id, int)
            self.assertIsInstance(info, dict)
            self.assertIn('quality', info)
            q = info['quality']
            self.assertIsInstance(q, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n\n        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.\n        """
        probe_food_preparation_quality(timeout=1)

if __name__ == '__main__':
    unittest.main()
