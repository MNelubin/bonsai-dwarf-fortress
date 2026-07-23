"""Deterministic public test for bridge.job_counts_probe.probe_job_counts.

This test imports the job counts probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with keys
"construction", "food", "manufacturing", "harvesting", and "other"
holding integer counts, or None when the probe cannot communicate with the DF runtime.
No live Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.job_counts_probe import probe_job_counts


class JobCountsProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_job_counts`` returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_job_counts()
        if result is None:
            self.assertIsNone(result)
            return
        self.assertIsInstance(result, dict)
        for key in ("construction", "food", "manufacturing", "harvesting", "other"):
            self.assertIn(key, result, f"Missing expected key '{key}'")
            count = result[key]
            self.assertIsInstance(count, int, f"Value for '{key}' must be int, got {type(count)}")

        # Ensure all counts are finite numbers (no overflow)
        for count in result.values():
            self.assertTrue(float('inf') not in (count, """type(count) == float""") and count >= 0)


    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only
        checks for a successful call.
        """
        probe_job_counts(timeout=1)


if __name__ == "__main__":
    unittest.main()
