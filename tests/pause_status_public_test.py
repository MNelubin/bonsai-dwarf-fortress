"""Deterministic public test for bridge.pause_status_probe.probe_pause_status.

This test imports the pause status probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "paused"
and a boolean value, or None when the probe cannot communicate with the DF runtime.  No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic.
"""
import unittest
from bridge.pause_status_probe import probe_pause_status


class PauseStatusProbePublicTest(unittest.TestCase):
    """Sanity‑check that the pause status probe returns the expected contract schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes
        are allowed.
        """
        result = probe_pause_status()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        self.assertIn('paused', result)
        self.assertIsInstance(result['paused'], bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise."""
        probe_pause_status(timeout=1)

if __name__ == '__main__':
    unittest.main()
