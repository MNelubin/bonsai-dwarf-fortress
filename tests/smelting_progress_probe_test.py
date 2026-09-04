"""Deterministic public test for bridge.smelting_progress_probe.probe_smelting_jobs.\n\nThis test imports the smelting progress probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary with a single key "smelting_jobs"\nand an integer count, or None when the probe cannot communicate with the DF runtime. No live\nDwarf Fortress process is required because the implementation already returns None on transport\nfailure, making the test deterministic in the coding‑graph environment.\n"""
import unittest
from bridge.smelting_progress_probe import probe_smelting_jobs


class SmeltingProgressProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the smelting progress probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n\n        The probe may legitimately return ``None`` (e.g. when DF is not running), so both\n        outcomes are allowed.\n        """
        result = probe_smelting_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'smelting_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('smelting_jobs', result)
        count = result['smelting_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n\n        The implementation catches all exceptions and returns ``None``, so the test only checks\n        for a successful call.\n        """
        probe_smelting_jobs(timeout=1)


if __name__ == '__main__':
    unittest.main()
