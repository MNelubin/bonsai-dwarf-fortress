"""
Test for bridge.baseline_rules.collect_baseline

Ensures the function returns the expected keys and correct handling of the cpu_time attribute.
"""

from bridge.baseline_rules import collect_baseline

class DummyState:
    cpu_time: float


def test_collect_baseline_basic():
    state = DummyState()
    state.cpu_time = 123.45
    result = collect_baseline(seed=42, game_state=state)
    assert result == {"seed": 42, "cpu_seconds": 123.45, "worst_cpu": True, "failure_taxonomy": []}


def test_collect_baseline_missing_attribute():
    class NoCpuState:
        pass

    result = collect_baseline(seed=7, game_state=NoCpuState())
    assert result == {"seed": 7, "cpu_seconds": 0.0, "worst_cpu": False, "failure_taxonomy": []}
