"""
Deterministic public test for bridge.finish_probe.probe_finished.

This test imports the probe implementation, calls it with the default timeout,
and verifies that the returned value conforms to the expected contract: either
"{"finished": bool}" or ``None`` when the probe cannot communicate with the
DFHack process.  No live Dwarf Fortress instance is required because the
implementation already handles communication failures safely.
"""

import unittest
from bridge.finish_probe import probe_finished


class FinishProbePublicTest(unittest.TestCase):
    """Validate the public API of ``probe_finished``."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and ensure the output matches the contract."""
        result = probe_finished()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn("finished", result)
            finished = result["finished"]
            self.assertIsInstance(finished, bool)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non-default timeout parameter does not raise."""
        probe_finished(timeout=1)


if __name__ == "__main__":
    unittest.main()
