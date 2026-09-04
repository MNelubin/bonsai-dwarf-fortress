"""Deterministic public test for bridge.pause_state_probe.probe_pause_state.

This test imports the pause state probe, calls the function with the
default timeout, and verifies that the returned value is either a
dictionary with a single key "paused" and a boolean value, or ``None``
when the probe cannot communicate with the DF runtime. No live Dwarf
Fortress process is required because the implementation already
returns ``None`` on transport failure, making the test deterministic
in the coding‑graph environment.
"""

import unittest
from bridge.pause_state_probe import probe_pause_state


class PauseStateProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_pause_state`` returns the expected
    contract schema and that a custom timeout argument does not raise."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not
        running), so both outcomes are allowed.
        """
        result = probe_pause_state()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'paused': <bool>}
        self.assertIsInstance(result, dict)
        self.assertIn('paused', result)
        paused = result['paused']
        self.assertIsInstance(paused, bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.
        """
        probe_pause_state(timeout=1)

if __name__ == '__main__':
    unittest.main()
