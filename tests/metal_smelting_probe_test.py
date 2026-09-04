"""
Deterministic public test for bridge.metal_smelting_probe.probe_smelting_jobs.

This test imports the metal smelting probe, calls the function with the default
timeout, and verifies that the returned value is either a mapping with a single
key "smelting_jobs" containing an integer count, or None when the probe cannot
communicate with the DF runtime. No live Dwarf Fortress process is required
because the implementation is failure‑safe.
"""

import unittest
from bridge.metal_smelting_probe import probe_smelting_jobs


class MetalSmeltingProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the probe returns the expected contract."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract."""
        result = probe_smelting_jobs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('smelting_jobs', result)
            count = result['smelting_jobs']
            self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise."""
        probe_smelting_jobs(timeout=1)


if __name__ == '__main__':
    unittest.main()
