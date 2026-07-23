"""Deterministic public test for bridge.labour_probe.probe_labour_counts.

This test imports the new labour probe, calls the function with default timeout,
and verifies that the returned value is either a dictionary mapping labour names
to non‑negative integer counts, or ``None`` when the probe cannot communicate
with the DF runtime. No live Dwarf Fortress process is required because the
implementation already returns ``None`` on transport failure, making the test
deterministic in the coding‑graph environment.
"""
import unittest
from bridge.labour_probe import probe_labour_counts


class LabourProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that ``probe_labour_counts`` returns the expected schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract."""
        result = probe_labour_counts()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            for labour, count in result.items():
                self.assertIsInstance(labour, str)
                self.assertIsInstance(count, int)
                self.assertGreaterEqual(count, 0, f"Count for '{labour}' must be non‑negative")

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_labour_counts(timeout=1)


if __name__ == "__main__":
    unittest.main()
