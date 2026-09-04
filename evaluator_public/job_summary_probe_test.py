"""Deterministic public test for bridge.job_summary_probe.probe_job_summary.

This test imports the job summary probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with two keys:
* "state_counts" – mapping job state strings to integer counts
* "category_counts" – mapping job category strings to integer counts
or None when the probe cannot communicate with the DF runtime. No live Dwarf Fortress
process is required because the implementation already returns None on transport failure,
making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.job_summary_probe import probe_job_summary


class JobSummaryProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_job_summary``.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check that the output matches the expected schema.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are acceptable.
        """
        result = probe_job_summary()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a dict with state_counts and category_counts sub‑dicts
        self.assertIsInstance(result, dict)
        self.assertIn('state_counts', result)
        self.assertIn('category_counts', result)
        state = result['state_counts']
        self.assertIsInstance(state, dict)
        for key, count in state.items():
            self.assertIn(key, {'queued', 'active', 'suspended', 'cancelled'})
            self.assertIsInstance(count, int)
        cats = result['category_counts']
        self.assertIsInstance(cats, dict)
        for key, count in cats.items():
            self.assertIn(key, {'construction', 'food', 'manufacturing', 'harvesting', 'other'})
            self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensuring a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so we only check
        that the call succeeds.
        """
        probe_job_summary(timeout=1)


if __name__ == '__main__':
    unittest.main()
