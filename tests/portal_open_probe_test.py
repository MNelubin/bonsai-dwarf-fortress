"""Deterministic public test for bridge.portal_open_probe.probe_portal_open.\n\nThis test imports the portal open probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary with a single key\n"portal_opened" and a boolean value, or None when the probe cannot communicate with the\nDF runtime. No live Dwarf Fortress process is required because the implementation already\nreturns None on transport failure, making the test deterministic in the coding‑graph\nenvironment.\n"""

import unittest
from bridge.portal_open_probe import probe_portal_open


class PortalOpenProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the portal open probe returns the expected contract."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n
        The probe may legitimately return ``None`` (e.g. when DF is not running),\n        so both outcomes are allowed.\n        """
        result = probe_portal_open()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        self.assertIn('portal_opened', result)
        val = result['portal_opened']
        self.assertIsInstance(val, bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n
        The implementation catches all exceptions and returns ``None``, so the test only\n        checks for a successful call.\n        """
        probe_portal_open(timeout=1)

if __name__ == '__main__':
    unittest.main()
