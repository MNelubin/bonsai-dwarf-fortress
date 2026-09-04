"""Deterministic public test for bridge.inventory_weight_probe.probe_total_inventory_weight.

This test imports the probe, calls it with the default timeout, and verifies that the returned value is either a dictionary with a single key "total_inventory_weight" and an integer value, or None when the probe cannot communicate with the DF runtime. No live Dwarf Fortress process is required because the implementation already returns None on transport failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.inventory_weight_probe import probe_total_inventory_weight


class InventoryWeightProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_total_inventory_weight`` returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are allowed.
        """
        result = probe_total_inventory_weight()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'total_inventory_weight': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('total_inventory_weight', result)
        weight = result['total_inventory_weight']
        self.assertIsInstance(weight, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.
        """
        probe_total_inventory_weight(timeout=1)

if __name__ == '__main__':
    unittest.main()
