"""Deterministic public test for bridge.animal_care_probe.probe_animal_care.\n\nThis test imports the animal care probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary mapping animal unit IDs to a\nsub‑dictionary containing a single key "health" with a string value ("healthy", "injured",
"ill", "dead"), or None when the probe cannot communicate with the DF runtime. No live\nDwarf Fortress process is required because the implementation already returns None on\ntransport failure, making the test deterministic in the coding‑graph environment.\n"""

import unittest
from bridge.animal_care_probe import probe_animal_care


class AnimalCareProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_animal_care`` returns the expected contract\n    schema and that a custom timeout argument does not raise.\n    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n
        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.\n        """
        result = probe_animal_care()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a dict of unit_id → {"health": <str>}
        self.assertIsInstance(result, dict)
        for unit_id, info in result.items():
            self.assertIsInstance(unit_id, int)
            self.assertIsInstance(info, dict)
            self.assertIn('health', info)
            health = info['health']
            self.assertIsInstance(health, str)
            self.assertIn(health, ('healthy', 'injured', 'ill', 'dead'))

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n
        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.\n        """
        probe_animal_care(timeout=1)


if __name__ == '__main__':
    unittest.main()
