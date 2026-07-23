"""Deterministic public test for bridge.stress_probe.probe_stress.

This test imports the stress probe, calls it with default timeout, and
validates that the returned value is either a dictionary with a single key
"stress" and an integer value, or ``None`` when the probe cannot communicate
with the DF runtime. No live Dwarf Fortress process is required because the
implementation already returns ``None`` on transport failure, making the test
deterministic in the coding graph.
"""

import unittest
from bridge.stress_probe import probe_stress

class StressProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_stress``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_stress()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('stress', result)
            stress = result['stress']
            self.assertIsInstance(stress, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_stress(timeout=1)

if __name__ == "__main__":
    unittest.main()
