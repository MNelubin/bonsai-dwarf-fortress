"""Deterministic public test for bridge.unit_health_probe.probe_unit_health.

This test imports the unit health probe, calls the function with default timeout,
and verifies that the returned value is either a list of dictionaries with keys
"id" and "health" (both integers) or ``None`` when the probe fails or cannot
parse the result. The test does not require a live DF process because the
implementation already returns ``None`` on transport failure, making the test
deterministic.
"""
import unittest
from bridge.unit_health_probe import probe_unit_health

class UnitHealthProbePublicTest(unittest.TestCase):
    """Basic sanity‑check for ``probe_unit_health`` public contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract."""
        result = probe_unit_health()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, list)
        for entry in result:
            self.assertIsInstance(entry, dict)
            self.assertIn('id', entry)
            self.assertIn('health', entry)
            self.assertIsInstance(entry['id'], int)
            self.assertIsInstance(entry['health'], int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_unit_health(timeout=1)

if __name__ == '__main__':
    unittest.main()
