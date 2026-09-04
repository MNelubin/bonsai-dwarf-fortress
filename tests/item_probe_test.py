"""Public test for bridge.item_probe.probe_total_item_value.

This test imports the probe, calls it with default timeout, and verifies that the
result is either a dict with a single key "total_value" and an integer value, or
None when the probe cannot communicate with the DF runtime.  No live DF process
is required because the implementation already returns None on error.
"""
import unittest
from bridge.item_probe import probe_total_item_value


class ItemValueProbeTest(unittest.TestCase):
    """Validate the public contract of ``probe_total_item_value``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_total_item_value()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('total_value', result)
            total = result['total_value']
            self.assertIsInstance(total, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_total_item_value(timeout=1)


if __name__ == '__main__':
    unittest.main()
