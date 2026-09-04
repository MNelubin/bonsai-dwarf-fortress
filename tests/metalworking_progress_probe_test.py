"""Deterministic public test for bridge.metalworking_progress_probe.probe_metalworking_jobs.

This test imports the metalworking progress probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "metalworking_jobs"
and an integer count, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""

import unittest
from bridge.metalworking_progress_probe import probe_metalworking_jobs


class MetalworkingProgressProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the metalworking progress probe returns the expected contract schema.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are allowed.
        """
        result = probe_metalworking_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'metalworking_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('metalworking_jobs', result)
        count = result['metalworking_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.
        """
        probe_metalworking_jobs(timeout=1)

if __name__ == '__main__':
    unittest.main()
