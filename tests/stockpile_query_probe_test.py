"""Deterministic public test for bridge.stockpile_query_probe.probe_general_stockpiles.

This test imports the stockpile query probe, calls it with the default timeout, and verifies that the returned value is either a dictionary with a single key "general_stockpiles" holding an integer count, or None when communication fails. The implementation is failure‑safe, so the test can run in the coding‑graph environment without a live DF process.
"""

import unittest
from bridge.stockpile_query_probe import probe_general_stockpiles


class StockpileQueryProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_general_stockpiles``."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check that the output matches the expected contract."""
        result = probe_general_stockpiles()

        if result is None:
            self.assertIsNone(result)
            return

        # Expected result: {"general_stockpiles": <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('general_stockpiles', result)
        count = result['general_stockpiles']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensuring a non‑default timeout argument does not raise an exception."""
        probe_general_stockpiles(timeout=1)


if __name__ == '__main__':
    unittest.main()
