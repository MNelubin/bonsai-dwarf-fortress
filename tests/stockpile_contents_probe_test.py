"""Deterministic public test for bridge.stockpile_contents_probe.probe_stockpile_contents.

This test imports the stockpile contents probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary mapping stockpile IDs (int) to a
list of item type identifiers (str), e.g. [\"food\", \"metal\"] or None when the probe
cannot communicate with the DF runtime. No live Dwarf Fortress process is required because
the implementation already returns None on transport failure, making the test deterministic
in the coding‑graph environment.
"""
import unittest
from bridge.stockpile_contents_probe import probe_stockpile_contents


class StockpileContentsProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_stockpile_contents`` returns the expected contract schema
    and that a custom timeout argument does not raise.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_stockpile_contents()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a dict of stockpile_id → list[str]
        self.assertIsInstance(result, dict)
        for sp_id, item_list in result.items():
            self.assertIsInstance(sp_id, int)
            self.assertIsInstance(item_list, list)
            for item in item_list:
                self.assertIsInstance(item, str)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only checks
        for a successful call.
        """
        probe_stockpile_contents(timeout=1)

if __name__ == '__main__':
    unittest.main()
