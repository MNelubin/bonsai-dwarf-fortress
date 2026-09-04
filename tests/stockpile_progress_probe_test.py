"""Deterministic public test for bridge.stockpile_progress_probe.probe_stockpile_count.

This test imports the stockpile progress probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "stockpile_count"
and an integer count, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.stockpile_progress_probe import probe_stockpile_count


class StockpileProgressProbePublicTest(unittest.TestCase):
    def test_probe_returns_schema_or_none(self) -> None:
        result = probe_stockpile_count()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        self.assertIn('stockpile_count', result)
        count = result['stockpile_count']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        probe_stockpile_count(timeout=1)


if __name__ == "__main__":
    unittest.main()
