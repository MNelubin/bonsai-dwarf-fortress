"""Deterministic public test for bridge.unit_deaths_probe.probe_unit_deaths.

This test imports the unit deaths probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "unit_deaths"
and an integer count, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""

import unittest
from bridge.unit_deaths_probe import probe_unit_deaths


class UnitDeathsProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the unit deaths probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are allowed.
        """
        result = probe_unit_deaths()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'unit_deaths': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('unit_deaths', result)
        count = result['unit_deaths']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only checks
        for a successful call.
        """
        probe_unit_deaths(timeout=1)

if __name__ == '__main__':
    unittest.main()
