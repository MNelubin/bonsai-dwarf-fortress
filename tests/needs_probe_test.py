"""Deterministic public test for bridge.needs_probe.probe_dire_needs.\n\nThis test imports the dire‑needs probe, calls the function with the default\ntimeout, and verifies that the returned value is either a list of unit IDs\n(in the order provided by DF) or ``None`` when the probe cannot communicate\nwith the DF runtime. No live Dwarf Fortress process is required because the\nprobe returns "None" on transport failure, making the test deterministic
in the coding‑graph environment.\n"""
import unittest
from bridge.needs_probe import probe_dire_needs


class NeedsProbePublicTest(unittest.TestCase):
    """Basic sanity‑check for ``probe_dire_needs``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_dire_needs()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, list)
            for unit_id in result:
                self.assertIsInstance(unit_id, int)
                # The probe may legitimately return an empty list.
                # Ensure we are dealing with integers, not dicts.
    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_dire_needs(timeout=1)

if __name__ == '__main__':
    unittest.main()
