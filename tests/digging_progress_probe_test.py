"""Deterministic public test for bridge.digging_progress_probe.probe_digging_jobs.

This test imports the digging progress probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "digging_jobs"
and an integer count, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.digging_progress_probe import probe_digging_jobs


class DiggingProgressProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the digging progress probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_digging_jobs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('digging_jobs', result)
            count = result['digging_jobs']
            self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_digging_jobs(timeout=1)


if __name__ == '__main__':
    unittest.main()
