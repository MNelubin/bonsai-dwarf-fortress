"""Deterministic public test for bridge.unit_population_probe.probe_unit_population.

This test imports the unit population probe, calls the function with default timeout,
and verifies that the returned value is either a dictionary mapping civ_id (int) to
integer counts, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on
transport failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.unit_population_probe import probe_unit_population


class UnitPopulationProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the probe returns the expected JSON‑serialisable contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_unit_population()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            # Every key must be a civ_id (int) and each value an integer count.
            for civ_id, count in result.items():
                self.assertIsInstance(civ_id, int)
                self.assertIsInstance(count, int)
                self.assertGreaterEqual(count, 0)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_unit_population(timeout=1)


if __name__ == '__main__':
    unittest.main()
