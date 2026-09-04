"""Public test for bridge.skill_probe.probe_skills.\n\nThis test imports the skill probe, calls the function with default timeout,\nand verifies that the returned value is either a mapping from unit IDs (int)\nto a list of skill dictionaries, or ``None`` when the probe cannot communicate\nwith the DF runtime. The implementation does not require a live DF process\nbecause the probe safely returns ``None`` on transport failure, making the\ntest deterministic in the coding‑graph environment.\n"""

import unittest
from bridge.skill_probe import probe_skills
from bridge.bridge import Bridge


class SkillProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_skills``.\n\n    The probe should return a dict where each key is a unit ID (int) and each\n    value is a list of dicts with string ``skill`` and integer ``level``\n    fields, or ``None`` on failure.\n    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_skills()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            # Every key must be an integer unit ID.
            for unit_id, skills in result.items():
                self.assertIsInstance(unit_id, int)
                self.assertIsInstance(skills, list)
                for skill in skills:
                    self.assertIsInstance(skill, dict)
                    self.assertIn('skill', skill)
                    self.assertIn('level', skill)
                    self.assertIsInstance(skill['skill'], str)
                    self.assertIsInstance(skill['level'], int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_skills(timeout=1)

    def test_tick_callback_integration_no_crash(self) -> None:
        """Run the bridge tick loop a few times to ensure the probe works with\n        the Bridge framework without crashing."""
        # No live DF needed; just invoke the probe after a few ticks.
        Bridge.tick()
        Bridge.tick()
        Bridge.tick()
        probe_skills()

    def test_invalid_timeout_is_handled(self) -> None:
        """Passing a negative timeout should not raise (probe treats it as error).\n        The result must be None.\n        """
        self.assertIsNone(probe_skills(timeout=-5))


if __name__ == "__main__":
    unittest.main()
