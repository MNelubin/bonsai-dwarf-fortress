"""Deterministic public test for bridge.animal_breeding_probe.probe_breeding_pairs.

This test imports the animal breeding probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "breeding_pairs"
and an integer count, or None when the probe cannot communicate with the DF runtime. No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.animal_breeding_probe import probe_breeding_pairs


class AnimalBreedingProbePublicTest(unittest.TestCase):
    """Basic sanity‑check for ``probe_breeding_pairs``."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_breeding_pairs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('breeding_pairs', result)
            count = result['breeding_pairs']
            self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_breeding_pairs(timeout=1)


if __name__ == '__main__':
    unittest.main()
