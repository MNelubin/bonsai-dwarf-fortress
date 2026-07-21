"""Focused fake-backend tests for EpisodeRunner.

These tests verify:
* call order routing through the supplied backend
* error termination when limits are hit
* no hidden fallback to the stub backend
* replay-identical output for injected backends
"""

import copy
import pytest

from game_runner.backend import BackendProtocolError, ScriptedEpisodeBackend
from game_runner.episode_runner import EpisodeRunner


class EchoBackend(ScriptedEpisodeBackend):
    """Backend that simply echoes the action and number of ticks.
    Used to verify that EpisodeRunner forwards calls correctly.
    """
    def __init__(self):
        # Empty sequences force the base class to raise on any observation/act call.
        super().__init__([], [])

    def observe(self) -> dict:
        return {"echo": "observe"}

    def act(self, action: dict) -> dict:
        return {"action": action}

    def advance(self, ticks: int) -> dict:
        return {"ticks": ticks}


@pytest.fixture
def echo_backend():
    return EchoBackend()


    def test_backend_injection_call_order(echo_backend):
        """Runner must forward observe → act → advance in the exact sequence provided."""
        runner = EpisodeRunner(backend=echo_backend, seed=42, max_steps=3)
        obs = runner.run_step(action=None)
        act = runner.run_step(action={"cmd": "foo"})
        adv = runner.run_step(action=None)
        assert obs == {"echo": "observe"}
        # The runner performs act followed by advance, so the returned value
        # is the result of ``advance`` (ticks echo).
        assert act == {"ticks": 1}
        assert adv == {"echo": "observe"}



def test_backend_error_termination_on_step_limit(echo_backend):
    """Exceeding max_steps should raise BackendProtocolError immediately, no
    further backend interactions."""
    runner = EpisodeRunner(backend=echo_backend, seed=0, max_steps=1)
    # First step succeeds.
    runner.run_step(action=None)
    # Second step hits the limit.
    with pytest.raises(BackendProtocolError, match="maximum number of steps"):
        runner.run_step(action={"cmd": "spam"})


def test_no_hidden_fallback_when_backend_invalid(echo_backend):
    """If the runner receives a None backend it must not fall back to the stub;
an informative error should be raised instead."""
    with pytest.raises(TypeError, match="backend must implement the EpisodeBackend protocol"):
        EpisodeRunner(backend=None)


def test_replay_identical_output(echo_backend):
    """Repeated runs with the same backend should produce identical observable
    outputs, ensuring deterministic replay."""
    runner1 = EpisodeRunner(backend=echo_backend, seed=7, max_steps=3)
    runner2 = EpisodeRunner(backend=echo_backend, seed=7, max_steps=3)
    # Run the exact same sequence.
    out1 = runner1.run_step(action=None)
    out2 = runner2.run_step(action=None)          # should match out1
    out3 = runner1.run_step(action={"a": 1})
    out4 = runner2.run_step(action={"a": 1})     # should match out3
    assert out1 == out2 == {"echo": "observe"}
    assert out3 == out4 == {"action": {"a": 1}}


def test_backend_ledger_is_replayable(echo_backend):
    """Ledger returned by the injected backend must be deep-copied and thus
    replayable without mutation."""
    runner = EpisodeRunner(backend=echo_backend, seed=0, max_steps=3)
    ledger = copy.deepcopy(runner.get_ledger())
    _ = runner.run_step(action=None)
    _ = runner.run_step(action={"x": 1})
    _ = runner.run_step(action=None)
    assert ledger == runner.get_ledger()   # unchanged copy
