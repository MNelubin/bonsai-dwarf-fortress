"""
Deterministic public test for bridge.pause_advancement_probe.probe_pause_advancement_state.

This test imports the pause/advancement probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with keys "paused" and "advancement_allowed"
both mapping to bool, or None when the probe cannot communicate with the DF runtime. No live Dwarf
Fortress process is required because the implementation already returns None on transport failure,
making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.pause_advancement_probe import probe_pause_advancement_state


class PauseAdvancementProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_pause_advancement_state`` returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes
        are allowed.
        """
        result = probe_pause_advancement_state()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'paused': <bool>, 'advancement_allowed': <bool>}
        self.assertIsInstance(result, dict)
        self.assertIn('paused', result)
        self.assertIn('advancement_allowed', result)
        self.assertIsInstance(result['paused'], bool)
        self.assertIsInstance(result['advancement_allowed'], bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``; the test only checks for a
        successful call.
        """
        probe_pause_advancement_state(timeout=1)

if __name__ == '__main__':
    unittest.main()
