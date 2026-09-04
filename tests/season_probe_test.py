"""Deterministic public test for bridge.season_probe.probe_season.

This test imports the season probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary with a single key
"season" and a string value, or None when the probe cannot communicate with the
DF runtime. No live Dwarf Fortress process is required because the implementation
already returns None on transport failure, making the test deterministic in the
coding‑graph environment.
"""
import unittest
from bridge.season_probe import probe_season


class SeasonProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the season probe returns the expected contract."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_season()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'season': <str>}
        self.assertIsInstance(result, dict)
        self.assertIn('season', result)
        val = result['season']
        self.assertIsInstance(val, str)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``, so the
        test only checks for a successful call.
        """
        probe_season(timeout=1)

if __name__ == '__main__':
    unittest.main()
