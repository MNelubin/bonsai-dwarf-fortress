"""
Public test for bridge.weather_probe.probe_weather.

This test imports the weather probe, runs it with default timeout, and validates that the
returned object follows the expected contract: a dictionary containing the keys
"is_rainy", "is_stormy", "is_snowy", "temperature" and "humidity", or None when
communication with the DF runtime fails. No live DF process is required; the probe
already handles transport errors deterministically.
"""
import unittest
from bridge.weather_probe import probe_weather

class WeatherProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_weather``."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_weather()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            expected_keys = {
                "is_rainy",
                "is_stormy",
                "is_snowy",
                "temperature",
                "humidity",
            }
            self.assertTrue(expected_keys.issubset(result.keys()))
            # Verify types of scalar entries.
            for name in ("is_rainy", "is_stormy", "is_snowy"):
                self.assertIsInstance(result[name], bool)
            for name in ("temperature", "humidity"):
                self.assertIsInstance(result.get(name), (int, type(None)))

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_weather(timeout=1)


if __name__ == "__main__":
    unittest.main()
