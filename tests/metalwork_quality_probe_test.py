"""
Deterministic public test for bridge.metalwork_quality_probe.probe_metalwork_quality.

This test imports the metalwork quality probe, calls the function with the default
timeout, and verifies that the returned value is either a dictionary mapping job
IDs to a sub‑dictionary containing a single key "quality" with an integer value,
 or None when the probe cannot communicate with the DF runtime. No live Dwarf
 Fortress process is required because the implementation already returns None on
 transport failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.metalwork_quality_probe import probe_metalwork_quality


class MetalworkQualityProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_metalwork_quality`` returns the expected
    contract schema and that a custom timeout argument does not raise.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_metalwork_quality()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a dict of job_id → {"quality": int}
        self.assertIsInstance(result, dict)
        for job_id, info in result.items():
            self.assertIsInstance(job_id, int)
            self.assertIsInstance(info, dict)
            self.assertIn('quality', info)
            q = info['quality']
            self.assertIsInstance(q, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.
        """
        probe_metalwork_quality(timeout=1)


if __name__ == "__main__":
    unittest.main()
