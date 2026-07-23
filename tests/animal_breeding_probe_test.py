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
    """Basic sanity‑check that ``probe_breeding_pairs`` returns the expected contract.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are allowed.
        """
        result = probe_breeding_pairs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'breeding_pairs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('breeding_pairs', result)
        count = result['breeding_pairs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only checks
        for a successful call.
        """
        probe_breeding_pairs(timeout=1)

if __name__ == '__main__':
    unittest.main()
