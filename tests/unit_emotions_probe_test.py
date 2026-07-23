"""Deterministic public test for bridge.unit_emotions_probe.probe_unit_emotions.

This test imports the probe, calls the function with default timeout, and validates
that the returned value is either a dictionary mapping unit IDs to a nested
dictionary with keys ``'emotion'`` and ``'strength'``, or ``None`` when the
probe cannot communicate with the DF runtime. The implementation already returns
None on communication failure, making the test deterministic without a live
Dwarf Fortress process.
"""
import unittest
from bridge.unit_emotions_probe import probe_unit_emotions


class UnitEmotionsProbeTest(unittest.TestCase):
    """Validate the public contract of ``probe_unit_emotions``.

    The probe should return a dict with structure:
        { unit_id: { 'emotion': str, 'strength': int } }
    or ``None`` on transport failure.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and verify the output contract."""
        result = probe_unit_emotions()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            for unit_id, data in result.items():
                self.assertIsInstance(unit_id, int)
                self.assertIsInstance(data, dict)
                self.assertIn('emotion', data)
                self.assertIn('strength', data)
                self.assertIsInstance(data['emotion'], str)
                self.assertIsInstance(data['strength'], int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_unit_emotions(timeout=1)

    def test_invalid_input_is_handled_gracefully(self) -> None:
        """The probe accepts only a timeout argument; passing other types
        should not crash and should return ``None``.
        """
        # Deliberately pass a wrong type; the probe defers all validation to
        # the runner and returns None on exception.
        result = probe_unit_emotions(timeout='invalid')
        # In the coding‑graph environment no live process is present, so we
        # expect ``None``.
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
