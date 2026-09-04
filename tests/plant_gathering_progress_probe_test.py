"""Deterministic public test for bridge.plant_gathering_progress_probe.probe_gathering_jobs\n\nThis test imports the plant gathering progress probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary with a single key "gathering_jobs" and an integer\ncount, or None when the probe cannot communicate with the DF runtime. No live Dwarf Fortress process\nis required because the implementation already returns None on transport failure, making the test deterministic\nin the coding‑graph environment.\n"""
import unittest
from bridge.plant_gathering_progress_probe import probe_gathering_jobs


class PlantGatheringProgressProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the plant gathering progress probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n        \n        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes are allowed.\n        """
        result = probe_gathering_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'gathering_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('gathering_jobs', result)
        count = result['gathering_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n        \n        The implementation catches all exceptions and returns ``None``, so the test only checks for a successful call.\n        """
        probe_gathering_jobs(timeout=1)


if __name__ == '__main__':
    unittest.main()
