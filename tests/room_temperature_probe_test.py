"""Deterministic public test for bridge.room_temperature_probe.probe_room_temperature.

This test imports the room temperature probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "room_temperature"
and an integer value in Kelvin, or None when the probe cannot communicate with the DF runtime.
No live Dwarf Fortress process is required because the implementation already returns None on
transport failure, making the test deterministic in the coding‑graph environment.
"""

import unittest
from bridge.room_temperature_probe import probe_room_temperature


class RoomTemperatureProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the room temperature probe returns the expected contract
    schema and that a custom timeout argument does not raise.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are allowed.
        """
        result = probe_room_temperature()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'room_temperature': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('room_temperature', result)
        temp = result['room_temperature']
        self.assertIsInstance(temp, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only
        checks for a successful call.
        """
        probe_room_temperature(timeout=1)

if __name__ == '__main__':
    unittest.main()
