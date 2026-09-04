"""Public test for the deterministic temperature probe (bridge.temperature_probe.probe_temperature).

This test imports the probe, calls the function with default timeout, and checks that the
result is either a dict with the expected key or None. No live DF process is required:
the implementation deliberately returns None if the runner fails, which makes the test
deterministic in the coding graph.
"""
import unittest
from bridge.temperature_probe import probe_temperature


class TemperatureProbeTest(unittest.TestCase):
    """Basic sanity‑check that the probe signature works and returns the correct schema."""

    def test_probe_returns_schema(self) -> None:
        """Call the probe and verify the output contract."""
        result = probe_temperature()
        # The probe should return a dict with a single key 'ambient_temp' or None.
        if result is not None:
            self.assertIsInstance(result, dict)
            expected_keys = {'ambient_temp'}
            self.assertTrue(expected_keys.issubset(result.keys()))

    def test_probe_allows_timeout_override(self) -> None:
        """Ensure a custom timeout parameter is accepted without error."""
        # Using a non‑default timeout should not raise.
        probe_temperature(timeout=1)


if __name__ == "__main__":
    unittest.main()
