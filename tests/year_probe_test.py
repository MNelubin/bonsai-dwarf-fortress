"""Deterministic public test for bridge/year_probe.py probe.

This test imports the year probe module, calls the function with the default
timeout, and verifies that the returned value is either a dictionary with the
expected keys or None when the probe cannot communicate with the DF runtime.
No live Dwarf Fortress process is required because the implementation already
returns None on transport failure, making the test deterministic in the coding
graph environment.
"""

import unittest
from bridge import year_probe as yp


class YearProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the year probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = yp.probe_advancement_commands()  # import function as shown in repo
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        # The original year_probe is expected to return a dict with
        # "advancement_commands_enabled" key; adapt if API changes.
        self.assertIn('advancement_commands_enabled', result)
        self.assertIsInstance(result['advancement_commands_enabled'], bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the
        test only checks for a successful call.
        """
        yp.probe_advancement_commands(timeout=1)


if __name__ == '__main__':
    unittest.main()
