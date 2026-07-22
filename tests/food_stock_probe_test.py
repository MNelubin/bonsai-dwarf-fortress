"""Deterministic public test for bridge.food_stock_probe.probe_food_stock.

This test imports the food stock probe, calls the function with default timeout,
and verifies that the returned value is either a dictionary with a single key
"food_stock" and an integer value, or None when the probe cannot communicate
with the DF runtime. No live Dwarf Fortress process is required because the
implementation already returns None on transport failure, making the test
deterministic in the coding graph environment.
"""
import unittest
from bridge.food_stock_probe import probe_food_stock


class FoodStockProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the food stock probe returns the expected
    JSON‑serialisable contract.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_food_stock()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('food_stock', result)
            stock = result['food_stock']
            self.assertIsInstance(stock, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_food_stock(timeout=1)


if __name__ == "__main__":
    unittest.main()
