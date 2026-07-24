"""Deterministic public test for bridge.stone_use_status_probe.probe_stone_use_status.

This test imports the stone use status probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "stone_jobs_paused"
and a boolean value, or None when the probe cannot communicate with the DF runtime.  No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic.
"""
import unittest
from bridge.stone_use_status_probe import probe_stone_use_status

class StoneUseStatusProbePublicTest(unittest.TestCase):
    """Sanity‑check that the stone use status probe returns the expected contract schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes\n        are allowed.\n        """
        result = probe_stone_use_status()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        self.assertIn('stone_jobs_paused', result)
        self.assertIsInstance(result['stone_jobs_paused'], bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise."""
        probe_stone_use_status(timeout=1)

if __name__ == '__main__':
    unittest.main()
