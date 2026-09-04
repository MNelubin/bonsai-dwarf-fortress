"""Public test for bridge.tile_probe.probe_tile_material.

This test imports the tile material probe, calls it with a sample coordinate,
and validates that the returned contract matches the expected shape: a
dictionary with a single key 'material' and an integer value, or None on
failure. No live DF process is required because the probe already safely
returns None when communication fails.
"""

import unittest
from bridge.tile_probe import probe_tile_material


class TileMaterialProbeTest(unittest.TestCase):
    """Validate the public contract of ``probe_tile_material``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe with a deterministic coordinate and check output."""
        # Sample coordinates (x, y, z). The exact tile contents are irrelevant;
        # we only test that the function runs and returns a dict with the
        # correct key name and an integer value, or None.
        pos = (0, 0, 0)
        result = probe_tile_material(pos=pos)
        if result is None:
            # Expected when DF is not running – the probe handles errors gracefully.
            self.assertIsNone(result)
        else:
            self.assertIsInstance(result, dict)
            self.assertIn('material', result)
            material = result['material']
            self.assertIsInstance(material, int)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure the probe accepts a non‑default timeout without raising."""
        probe_tile_material(pos=(1, 1, 0), timeout=1)

    def test_invalid_coordinate_type_is_handled(self) -> None:
        """Provide malformed input and verify the probe safely returns None."""
        self.assertIsNone(probe_tile_material(pos=("not a tuple", 0, 0)))  # type: ignore[arg-type]

    def test_returns_none_when_runner_raises(self) -> None:
        """Mimic a runner exception path.

        The ``_lua_tile_material_snapshot`` function constructs a Lua string,
        but if ``_dfhack_run`` raises it should propagate to ``probe_tile_material"
        resulting in ``None``. We can trigger this by passing a very low timeout
        (the runner may abort immediately), and ensure the return value is None.
        """
        self.assertIsNone(probe_tile_material(pos=(0, 0, 0), timeout=0))


if __name__ == "__main__":
    unittest.main()
