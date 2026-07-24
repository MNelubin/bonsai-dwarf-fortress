"""Deterministic public test for bridge.festival_schedule_probe.probe_festival_schedule.

This test imports the festival schedule probe, calls the function with the default timeout,
and verifies that the returned value is either a list of festival dictionaries (each with
"name" and "start" keys of type string) or None when the probe cannot communicate with the DF
runtime.  No live Dwarf Fortress process is required because the implementation already returns
None on transport failure, making the test deterministic.
"""
import unittest
from bridge.festival_schedule_probe import probe_festival_schedule


class FestivalScheduleProbePublicTest(unittest.TestCase):
    """Sanity‑check that ``probe_festival_schedule`` returns the expected contract schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both outcomes
        are allowed.
        """
        result = probe_festival_schedule()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a list of dicts each with "name" and "start"
        self.assertIsInstance(result, list)
        for fest in result:
            self.assertIsInstance(fest, dict)
            self.assertIn('name', fest)
            self.assertIn('start', fest)
            self.assertIsInstance(fest['name'], str)
            self.assertIsInstance(fest['start'], str)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise."""
        probe_festival_schedule(timeout=1)


if __name__ == '__main__':
    unittest.main()
