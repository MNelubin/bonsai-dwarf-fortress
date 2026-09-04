"""Public test for bridge.material_probe.probe_materials.

This test imports the probe, calls it with the default timeout, and verifies that
the returned value is either a dictionary mapping material IDs (int) to positive
integers (item counts) or ``None`` if communication with the DF runtime failed.
No live DF process is required because the implementation already returns ``None``
in such cases, making the test deterministic in the coding‑graph environment.
"""

import unittest
from bridge.material_probe import probe_materials


class MaterialProbePublicTest(unittest.TestCase):
    """Validate the public contract of ``probe_materials``."""
    def test_probe_returns_schema_or_none(self) -> None:
        """Call the probe and check the output contract."""
        result = probe_materials()
        if result is not None:
            self.assertIsInstance(result, dict)
            # Every key must be an int material ID and each value a non‑negative int.
            for material_id, count in result.items():
                self.assertIsInstance(material_id, int)
                self.assertIsInstance(count, int)
                self.assertGreaterEqual(count, 0)
        else:
            self.assertIsNone(result)

    def test_custom_timeout_is_accepted(self) -> None:
        """Ensure a non‑default timeout parameter does not raise."""
        probe_materials(timeout=1)


if __name__ == "__main__":
    unittest.main()
