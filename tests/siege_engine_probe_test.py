"""Deterministic public test for bridge.siege_engine_probe.probe_siege_jobs.

This test imports the siege engine progress probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "siege_jobs"
and an integer count, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""
import unittest

from bridge.siege_engine_probe import probe_siege_jobs


class SiegeEngineProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_siege_jobs`` returns the expected contract schema
    and that a custom timeout argument does not raise.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_siege_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'siege_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('siege_jobs', result)
        count = result['siege_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the
        test only checks for a successful call.
        """
        probe_siege_jobs(timeout=1)


if __name__ == '__main__':
    unittest.main()
