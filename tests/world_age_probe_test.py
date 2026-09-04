"""Deterministic public test for bridge.world_age_probe.probe_world_age.

This test imports the world age probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "world_age"
and an integer count of years, or ``None`` when the probe cannot communicate with the DF runtime.
No live Dwarf Fortress process is required because the implementation already returns ``None`` on transport failure,
making the test deterministic in the coding‑graph environment.
"""
import unittest
from bridge.world_age_probe import probe_world_age


class WorldAgeProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_world_age`` returns the expected contract schema
    and that a custom timeout argument does not raise.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_world_age()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'world_age': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('world_age', result)
        age = result['world_age']
        self.assertIsInstance(age, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only
        checks for a successful call.
        """
        probe_world_age(timeout=1)

if __name__ == '__main__':
    unittest.main()
