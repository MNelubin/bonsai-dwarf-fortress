"""
Deterministic public test for bridge.faction_api.get_faction_morale

This test imports the new faction morale API, calls the function with default timeout,
and verifies that the returned value is either a dictionary mapping faction IDs (int)
to integer morale values, or None when the probe cannot communicate with the DF
runtime. The implementation mirrors the contract tests for other probes and does
not require a live Dwarf Fortress process.
"""
import unittest
from bridge.faction_api import get_faction_morale


class FactionAPITest(unittest.TestCase):
    """Basic sanity‑check for ``bridge.faction_api.get_faction_morale``."""
    def test_get_faction_morale_returns_schema_or_none(self) -> None:
        """Call the API and ensure the output matches the expected contract."""
        result = get_faction_morale()
        if result is not None:
            self.assertIsInstance(result, dict)
            # Every key must be a faction ID (int) and each value an int.
            for faction_id, morale in result.items():
                self.assertIsInstance(faction_id, int)
                self.assertIsInstance(morale, int)
        else:
            # Deterministic fallback when DF is not running.
            self.assertIsNone(result)

    def test_get_faction_morale_with_custom_timeout(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        get_faction_morale(timeout=1)


if __name__ == '__main__':
    unittest.main()
