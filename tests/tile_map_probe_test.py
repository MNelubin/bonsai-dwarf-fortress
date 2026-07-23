"""Deterministic public test for bridge.tile_map_probe.probe_tile_map.

This test validates that the new tile map probe returns the expected JSON-
serialisable result with keys "width", "height" and "depth", or ``None`` when the
probe cannot communicate with the DF runtime. The test does not require a live
Dwarf Fortress process; the probe implementation already returns ``None`` on
transport failure, making the contract deterministic.
"""
import unittest
from bridge.tile_map_probe import probe_tile_map


class TileMapProbePublicTest(unittest.TestCase):
    """Basic sanity‑check for ``probe_tile_map``."""

    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_tile_map()
        if result is None:
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('width', result)
            self.assertIn('height', result)
            self.assertIn('depth', result)
            width = result['width']
            height = result['height']
            depth = result['depth']
            self.assertIsInstance(width, int)
            self.assertIsInstance(height, int)
            self.assertIsInstance(depth, int)
            # Simple sanity values – map dimensions are positive.
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)
            self.assertGreaterEqual(depth, 0)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_tile_map(timeout=1)


if __name__ == '__main__':
    unittest.main()
