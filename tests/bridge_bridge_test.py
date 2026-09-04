"""Deterministic public test for bridge.bridge.Bridge singleton.

This test imports the Bridge class, verifies that its public attributes exist,
and that a custom reset call works without raising an exception. No live Dwarf Fortress process
is required because Bridge only maintains an internal tick counter.
"""
import unittest
from bridge import Bridge


class BridgeSingletonPublicTest(unittest.TestCase):
    """Basic sanity‑check that the Bridge singleton respects its contract."""
    def test_public_attributes(self) -> None:
        """Check that 'finished' and '_ticks' are present and have correct types."""
        self.assertIn('finished', Bridge.__dict__)
        self.assertIn('_ticks', Bridge.__dict__)
        self.assertIsInstance(Bridge.finished, bool)
        self.assertIsInstance(Bridge._ticks, int)

    def test_reset_does_not_raise(self) -> None:
        """Calling Bridge.reset should not propagate exceptions."""
        # The implementation catches no exceptions, but resetting should be safe.
        Bridge.reset()
        self.assertFalse(Bridge.finished)
        self.assertEqual(Bridge._ticks, 0)


if __name__ == '__main__':
    unittest.main()
