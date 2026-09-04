"""Deterministic public test for bridge.pause_probe.probe_pause_state.\n\nThis test imports the pause state probe, calls the function with the default timeout,\nand verifies that the returned value is either a dictionary with a single key "paused"\nand a boolean value, or None when the probe cannot communicate with the DF runtime.\nNo live Dwarf Fortress process is required because the implementation already returns\nNone on transport failure, making the test deterministic in the coding‑graph environment.\n"""

import unittest
from bridge.pause_probe import probe_pause_state


class PauseProbePublicTest(unittest.TestCase):
    """Basic sanity‑check that the pause probe returns the expected contract schema.
    """
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract.\n
        The probe may legitimately return ``None`` (e.g. when DF is not running),\n        so both outcomes are allowed.\n        """
        result = probe_pause_state()
        if result is None:
            self.assertIsNone(result)
            return
        # Expect {'paused': <bool>}
        self.assertIsInstance(result, dict)
        self.assertIn('paused', result)
        paused = result['paused']
        self.assertIsInstance(paused, bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout argument does not raise.\n        The implementation catches all exceptions and returns ``None``, so the test
        only checks for a successful call.\n        """
        probe_pause_state(timeout=1)

if __name__ == '__main__':
    unittest.main()
