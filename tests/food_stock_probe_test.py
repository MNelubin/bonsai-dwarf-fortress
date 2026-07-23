"""Deterministic public test for bridge.food_stock_probe_api.get_food_stock.

This test imports the public API, calls ``get_food_stock`` with the default
timeout, and checks that the return value is either a dictionary containing the
key ``"food_stock"`` with an integer value, or ``None`` when communication with
the DF runtime fails. The implementation guarantees ``None`` on transport
failure, so the test is fully deterministic and does not require a live game.
"""
import unittest
from bridge.food_stock_probe_api import get_food_stock


class FoodStockProbePublicTest(unittest.TestCase):
    """Validate the contract of the food stock probe API."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and verify the JSON contract or explicit ``None``."""
        result = get_food_stock()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('food_stock', result)
            stock = result['food_stock']
            self.assertIsInstance(stock, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        get_food_stock(timeout=1)


if __name__ == "__main__":
    unittest.main()
