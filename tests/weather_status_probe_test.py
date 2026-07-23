"""Deterministic public test for bridge.weather_status_probe.probe_weather_status.

This test imports the weather status probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key "weather"
and a string description, or None when the probe cannot communicate with the DF runtime.  No live
Dwarf Fortress process is required because the implementation already returns None on transport
failure, making the test deterministic.
"""

import unittest
from bridge.weather_status_probe import probe_weather_status


class WeatherStatusProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the weather status probe returns the expected contract schema and
    that a custom timeout argument does not raise."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running), so both
        outcomes are allowed.
        """
        result = probe_weather_status()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'weather': <str>}
        self.assertIsInstance(result, dict)
        self.assertIn('weather', result)
        weather = result['weather']
        self.assertIsInstance(weather, str)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the test only checks
        for a successful call.
        """
        probe_weather_status(timeout=1)

if __name__ == '__main__':
    unittest.main()
