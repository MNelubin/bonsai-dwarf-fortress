"""Deterministic public test for bridge.current_time_probe.probe_current_time.

This test imports the current time probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "time"
and an integer value, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""

import unittest
from bridge.current_time_probe import probe_current_time


class CurrentTimeProbePublicTest(unittest.TestCase):
    """Sanity‑check that the current time probe returns the expected contract schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes
        are allowed.
        """
        result = probe_current_time()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        self.assertIn('time', result)
        self.assertIsInstance(result['time'], int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise."""
        probe_current_time(timeout=1)

if __name__ == '__main__':
    unittest.main()
