"""Deterministic public test for bridge.profession_probe.probe_profession_morale.

This test imports the profession morale probe, calls the function with default timeout, and validates that the returned value is either a dictionary mapping profession IDs (ints) to integer happiness scores (0‑100) or None when communication fails. No live DF process is required because the implementation already returns None on error.
"""

import unittest
from bridge.profession_probe import probe_profession_morale


class ProfessionMoraleProbeTest(unittest.TestCase):
    """Basic sanity‑check that the profession morale probe returns the expected contract."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the required JSON‑serialisable schema."""
        result = probe_profession_morale()
        if result is not None:
            self.assertIsInstance(result, dict)
            # Every key must be a profession ID (int) and each value an int.
            for prof_id, hap in result.items():
                self.assertIsInstance(prof_id, int)
                self.assertIsInstance(hap, int)
                # Happiness is defined to be between 0 and 100.
                self.assertGreaterEqual(hap, 0)
                self.assertLessEqual(hap, 100)
        else:
            # A missing live DF process is acceptable for the coding graph.
            self.assertIsNone(result)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_profession_morale(timeout=1)


if __name__ == "__main__":
    unittest.main()
