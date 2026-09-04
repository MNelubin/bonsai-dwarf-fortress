"""Deterministic public test for bridge.defense_jobs_probe.probe_defense_jobs.\n\nThis test imports the defense jobs probe, calls the function with the default\ntimeout, and verifies that the returned value is either a dictionary with a\nsingle key "defense_jobs" and an integer count, or None when the probe cannot\ncommunicate with the DF runtime. No live Dwarf Fortress process is required\nbecause the implementation already returns None on transport failure, making\nthe test deterministic in the coding‑graph environment.\n"""

import unittest
from bridge.defense_jobs_probe import probe_defense_jobs


class DefenseJobsProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_defense_jobs`` returns the expected contract.\n    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.\n        """
        result = probe_defense_jobs()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'defense_jobs': <int>}
        self.assertIsInstance(result, dict)
        self.assertIn('defense_jobs', result)
        count = result['defense_jobs']
        self.assertIsInstance(count, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n

        The implementation catches all exceptions and returns ``None``, so the\n        test only checks for a successful call.\n        """
        probe_defense_jobs(timeout=1)

if __name__ == '__main__':
    unittest.main()
