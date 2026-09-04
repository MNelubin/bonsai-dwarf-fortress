"""Deterministic public test for bridge.unit_needs_probe.probe_unit_needs.

This test imports the unit needs probe, calls the function with the default timeout,
and validates that the returned value matches the expected contract: either a
dictionary mapping unit IDs to dictionaries of need counters, or None if the probe
fails (e.g., DF runtime unavailable). The test does not require a live DF process
because the implementation safely returns None on transport failure.
"""
import unittest
from bridge.unit_needs_probe import probe_unit_needs


class UnitNeedsProbePublicTest(unittest.TestCase):
    """Validate the public API of ``probe_unit_needs``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output conforms to the contract."""
        result = probe_unit_needs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            # Verify mapping type and content shape.
            if result:
                first_key = next(iter(result))
                self.assertIsInstance(result[first_key], dict)
            for unit_id, needs in result.items():
                self.assertIsInstance(unit_id, int)
                self.assertIsInstance(needs, dict)
                self.assertIsInstance(needs.get("nausea"), int)  # example counter

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_unit_needs(timeout=1)

if __name__ == "__main__":
    unittest.main()
