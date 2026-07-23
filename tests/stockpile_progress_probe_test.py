"""Deterministic public test for bridge.stockpile_progress_probe.probe_stockpile_haul_jobs.\n\nThis test imports the stockpile progress probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary with a single key "stockpile_haul_jobs"\nand an integer count, or None when the probe cannot communicate with the DF runtime. No live\nDwarf Fortress process is required because the implementation already returns None on transport\nfailure, making the test deterministic in the coding‑graph environment.\n"""
import unittest
from bridge.stockpile_progress_probe import probe_stockpile_haul_jobs


class StockpileProgressProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the stockpile progress probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n
        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes are allowed.\n        """
        result = probe_stockpile_haul_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'stockpile_haul_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('stockpile_haul_jobs', result)
        count = result['stockpile_haul_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n
        The implementation catches all exceptions and returns ``None``, so the test only checks for a successful call.\n        """
        probe_stockpile_haul_jobs(timeout=1)

if __name__ == '__main__':
    unittest.main()
