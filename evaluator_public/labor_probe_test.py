"""
Deterministic public test for bridge.labor_probe.probe_labor.

This test imports the labor probe, calls the function with default timeout,
and verifies the returned contract – a mapping from unit ID to a set of
labor names, or None if the probe fails. No live DF process is required.
"""
import unittest
from bridge.labor_probe import probe_labor


class LaborProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the labor probe returns the expected schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract."""
        result = probe_labor()
        if result is not None:
            self.assertIsInstance(result, dict)
            for unit_id, labs in result.items():
                self.assertIsInstance(unit_id, int)
                self.assertIsInstance(labs, set)
                self.assertTrue(all(isinstance(name, str) for name in labs))
        else:
            self.assertIsNone(result)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_labor(timeout=1)


if __name__ == '__main__':
    unittest.main()
