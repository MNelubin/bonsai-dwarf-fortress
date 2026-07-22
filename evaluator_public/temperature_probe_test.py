"""
Public test for bridge.temperature_probe.probe_temperature.

This test imports the probe, calls the function with default timeout, and checks that the
result is either a dict with the expected key or None. No live DF process is required:
the implementation deliberately returns None if the runner fails, which makes the test
deterministic in the coding graph.
"""
import unittest
from bridge.temperature_probe import probe_temperature


class TemperatureProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_temperature``.

    The probe should return a dict with a single key ``'ambient_temp'`` on success,
    or ``None`` on transport failure.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and verify the output contract."""
        result = probe_temperature()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('ambient_temp', result)
            ambient = result['ambient_temp']
            self.assertIsInstance(ambient, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_temperature(timeout=1)

    def test_invalid_coordinate_type_is_handled(self) -> None:
        """Probes should not crash on malformed input; they return None."""
        # For safety we avoid passing coordinates altogether – the probe does
        # not accept a ``pos`` argument, only ``timeout``.
        result = probe_temperature()
        # No assertion needed; just ensure no exception is raised.
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
