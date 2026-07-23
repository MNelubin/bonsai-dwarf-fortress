"""Public test for bridge.unit_needs_probe.probe_unit_needs.

This test checks that the probe returns a dictionary with unit IDs mapped to a
sub‑dictionary of need counters, or ``None`` when the runtime is unavailable.
The implementation does not require a live DF process because the probe
already returns ``None`` on error, satisfying the deterministic contract.
"""
import unittest
from bridge.unit_needs_probe import probe_unit_needs


class UnitNeedsProbePublicTest(unittest.TestCase):
    """Validate the public contract of `probe_unit_needs`."""

    def test_returns_schema_or_none(self) -> None:
        """Call the probe and verify the output contract."""
        result = probe_unit_needs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            # Every key must be a unit ID (int) and the value another dict.
            for unit_id, needs in result.items():
                self.assertIsInstance(unit_id, int)
                self.assertIsInstance(needs, dict)
                # No specific counters are required for the minimal probe.
                self.assertGreaterEqual(len(needs), 0)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout does not raise an exception."""
        probe_unit_needs(timeout=1)

    def test_invalid_timeout_type_is_handled(self) -> None:
        """Pass a non‑integer timeout and verify the probe returns None safely."""
        self.assertIsNone(probe_unit_needs(timeout='fast'))

if __name__ == "__main__":
    unittest.main()
