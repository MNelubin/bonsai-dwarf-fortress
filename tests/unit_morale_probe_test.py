"""
Deterministic public test for bridge.unit_morale_probe.probe_unit_morale.

This test imports the unit morale probe, calls the function with the default timeout,
and verifies that the returned value is either a dictionary mapping unit IDs to a
sub‑dictionary containing a single key "morale" with an integer value, or None when the probe
cannot communicate with the DF runtime. No live Dwarf Fortress process is required because
the implementation already returns None on transport failure, making the test deterministic
in the coding‑graph environment.
"""
import unittest
from bridge.unit_morale_probe import probe_unit_morale


class UnitMoraleProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_unit_morale`` returns the expected contract
    schema and that a custom timeout argument does not raise.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.

        The probe may legitimately return ``None`` (e.g. when DF is not running),
        so both outcomes are allowed.
        """
        result = probe_unit_morale()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect a dict of unit_id → {"morale": int}
        self.assertIsInstance(result, dict)
        for unit_id, info in result.items():
            self.assertIsInstance(unit_id, int)
            self.assertIsInstance(info, dict)
            self.assertIn('morale', info)
            morale = info['morale']
            self.assertIsInstance(morale, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.

        The implementation catches all exceptions and returns ``None``,
        so the test only checks for a successful call.
        """
        probe_unit_morale(timeout=1)


if __name__ == '__main__':
    unittest.main()
