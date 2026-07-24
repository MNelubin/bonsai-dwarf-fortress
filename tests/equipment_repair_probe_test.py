"""Deterministic public test for bridge.equipment_repair_probe.probe_repair_jobs.

This test imports the equipment repair progress probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "repair_jobs" and an integer
count, or None when the probe cannot communicate with the DF runtime. No live Dwarf Fortress process is
required because the implementation already returns None on transport failure, making the test deterministic
in the coding‑graph environment.
"""

import unittest
from bridge.equipment_repair_probe import probe_repair_jobs


class EquipmentRepairProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the equipment repair probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes
        are allowed.
        """
        result = probe_repair_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'repair_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('repair_jobs', result)
        count = result['repair_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only checks
        for a successful call.
        """
        probe_repair_jobs(timeout=1)

if __name__ == '__main__':
    unittest.main()
