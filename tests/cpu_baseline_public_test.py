"""
Deterministic public test for the new CPU‑baseline mechanic.

The test imports the bridge implementation and verifies that the module exists,
that the public API function `collect_baseline` returns the expected keys,
and that running the bridge's tick loop for a fixed number of steps does not
raise an error.
"""
import bridge
import unittest


class CpuBaselinePublicTest(unittest.TestCase):
    """Simple sanity‑check test enforcing the existence of the CPU‑baseline API."""

    def test_api_presence(self):
        """Ensure the bridge singleton loads and the function is callable."""
        self.assertTrue(hasattr(bridge, "Bridge"), "Bridge singleton missing")
        # Dummy state with no cpu_time attribute to test fallback.
        class Dummy:
            pass
        result = bridge.collect_baseline(seed=0, game_state=Dummy())
        required = {"seed", "cpu_seconds", "worst_cpu", "failure_taxonomy"}
        self.assertTrue(all(k in result for k in required), \
                        f"Baseline result missing keys {required - result.keys()}")

    def test_tick_loop_no_error(self):
        """Run the bridge tick loop for a deterministic number of steps.

        This checks that the new `tick_callback` integration does not crash.
        """
        bridge.Bridge.tick()
        bridge.Bridge.tick()
        bridge.Bridge.tick()


if __name__ == "__main__":
    unittest.main()
