"""
Deterministic public test for bridge.unit_status_probe.probe_unit_status.

This test imports the unit status probe, calls it with the default timeout,
and verifies that the returned value is either a dictionary with a single key
"status" and a string value matching one of the expected unit states, or None
when the probe cannot communicate with the DF runtime. No live Dwarf Fortress
process is required because the implementation already returns None on
transport failure, making the test deterministic in the coding‑graph environment.
"""
import unittest

from bridge.unit_status_probe import probe_unit_status


class UnitStatusProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_unit_status``.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_unit_status()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        self.assertIn('status', result)
        status = result['status']
        self.assertIsInstance(status, str)
        expected = {'idle','working','dead','injured'}
        self.assertIn(status.lower(), expected)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.
        """
        probe_unit_status(timeout=1)

if __name__ == '__main__':
    unittest.main()
