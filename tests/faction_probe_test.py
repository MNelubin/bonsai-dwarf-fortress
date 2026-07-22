"""Deterministic public test for bridge.faction_probe.probe_faction_morale.

This test imports the faction morale probe, calls the function with default
timeout, and verifies that the returned value is either a mapping from faction
IDs (int) to integer morale values, or None when the probe cannot communicate
with the DF runtime. The implementation does not require a live DF process; it
relies on the probe's failure‑safe contract.
"""
import unittest
from bridge.faction_probe import probe_faction_morale


class FactionMoraleProbeTest(unittest.TestCase):
    """Basic sanity‑check that the probe returns the correct schema."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_faction_morale()
        if result is not None:
            self.assertIsInstance(result, dict)
            # Every key must be a faction ID (int) and each value an int.
            for faction_id, morale in result.items():
                self.assertIsInstance(faction_id, int)
                self.assertIsInstance(morale, int)
        else:
            # Deterministic fallback when DF is not running.
            self.assertIsNone(result)

    def test_probe_accepts_custom_timeout(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_faction_morale(timeout=1)


if __name__ == "__main__":
    unittest.main()
