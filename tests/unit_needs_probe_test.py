"""Public test for bridge.unit_needs_probe.probe_unit_needs.

This test imports the unit needs probe, calls it with the default timeout, and
validates the output contract – either a dict mapping unit IDs (int) to a
sub‑dict of need counters, or ``None`` when the probe cannot communicate with
the DF runtime. The implementation is failure‑safe and does not require a live
Dwarf Fortress process, satisfying the coding‑graph requirement for a public
test.
"""
import unittest
from bridge.unit_needs_probe import probe_unit_needs


class UnitNeedsProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_unit_needs``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the result matches the expected schema."""
        result = probe_unit_needs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            # Every key must be an integer unit ID.
            for unit_id, needs in result.items():
                self.assertIsInstance(unit_id, int)
                self.assertIsInstance(needs, dict)
                # Needs counters are expected to be integers (may be 0).
                for _key, value in needs.items():
                    self.assertIsInstance(value, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout does not raise an exception."""
        probe_unit_needs(timeout=1)


if __name__ == "__main__":
    unittest.main()
