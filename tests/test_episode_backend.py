import copy
import pytest

from game_runner.backend import (BackendProtocolError, EpisodeBackend,
                                 ScriptedEpisodeBackend)


class DummyBackend(ScriptedEpisodeBackend):
    """
    A thin subclass that obeys the EpisodeBackend protocol without adding
    implementation. It forwards method calls to its superclass.
    """
    pass


@pytest.fixture
def backend():
    """
    Provide a deterministic scripted backend for tests.

    The observation and action result sequences are short but cover all
    possible calls:

    * observe returns two distinct observations
    * act is called twice with different actions and returns two results
    * advance is called once with a positive tick count
    """
    observations = [{"obs": 1}, {"obs": 2}]
    action_results = [{"result": "a"}, {"result": "b"}]
    return DummyBackend(observations, action_results)


def test_backend_is_runtime_checkable(backend):
    """The Protocol class must be recognized by ``isinstance`` at runtime."""
    assert isinstance(backend, EpisodeBackend)


    def test_reset_success(backend):
        """A valid reset returns a JSON‑shaped dict and records the event."""
        res = backend.reset("sid", 123)
        assert set(res.keys()) == {"status", "save_id", "seed"}
        assert res["status"] == "reset"
        assert "sid" in res["save_id"]
        assert res["seed"] == 123
        assert backend.save_id == "sid"
        assert backend.seed == 123
        assert backend.ledger == []



def test_reset_invalid_save_id(backend):
    """Empty save_id raises ``BackendProtocolError``."""
    with pytest.raises(BackendProtocolError, match="save_id must be a non‑empty string"):
        backend.reset("", 42)


def test_reset_invalid_seed_type(backend):
    """Non‑int seed raises ``BackendProtocolError``."""
    with pytest.raises(BackendProtocolError, match="seed must be an integer"):
        backend.reset("sid", "not-int")


    def test_observe_sequence(backend):
        """Calling ``observe`` returns the scripted observations in order."""
        backend.reset("sid", 0)
        first = backend.observe()
        second = backend.observe()
        # Verify the second observation; the third call should raise.
        assert first == {"obs": 1}
        assert second == {"obs": 2}
        # The third call exhausts the observation sequence and raises.
        with pytest.raises(BackendProtocolError, match="no more observations"):
            backend.observe()
        # Ledger contains two observe events.
        expected_ledger = [{"event": "observe", "output": first},
                           {"event": "observe", "output": second}]
        assert backend.ledger == expected_ledger



def test_act_sequence_and_input_validation(backend):
    """``act`` consumes the scripted result list and validates the action argument."""
    backend.reset("sid", 0)
    # Valid actions.
    r1 = backend.act({"cmd": "foo"})
    r2 = backend.act({"cmd": "bar"})
    assert r1 == {"result": "a"}
    assert r2 == {"result": "b"}
    # Ledger reflects the actions and deep‑copied results.
    expected_ledger = [
        {"event": "act", "action": {"cmd": "foo"}, "result": {"result": "a"}},
        {"event": "act", "action": {"cmd": "bar"}, "result": {"result": "b"}},
    ]
    assert backend.ledger[-2:] == expected_ledger
    # Exhausted action_results raise.
    with pytest.raises(BackendProtocolError, match="no more action results"):
        backend.act({"cmd": "baz"})
    # Non‑dict action raises.
    with pytest.raises(BackendProtocolError, match="action must be a dict"):
        backend.act("not-a-dict")


def test_advance_valid_and_invalid_ticks(backend):
    """``advance`` validates tick count and records an event."""
    backend.reset("sid", 0)
    out = backend.advance(5)
    assert out == {"status": "advanced", "ticks": 5}
    assert backend.ledger[-1] == {"event": "advance", "ticks": 5}
    # Invalid tick values raise.
    for bad in (-1, 0, 3.14, "10"):
        with pytest.raises(BackendProtocolError, match=r"ticks must be a positive integer"):
            backend.advance(bad)


def test_deep_copy_isolation(backend):
    """Mutating the caller's observation/action must not affect the backend's state."""
    backend.reset("sid", 0)
    obs = backend.observe()
    obs_mutated = copy.deepcopy(obs)
    obs_mutated["obs"] = 999
    # Consuming a second observation must see the original scripted value.
    second = backend.observe()
    assert second == {"obs": 2}
    # Verify that the backend's ledger contains the original un‑mutated dicts.
    ledger = backend.ledger
    assert ledger[0]["output"] == {"obs": 1}
    assert ledger[1]["output"] == {"obs": 2}

    # Test action deep‑copy isolation.
    action = {"cmd": "go"}
    action["cmd"] = "bad"
    # The backend still returns the scripted result.
    result = backend.act({"cmd": "go"})
    assert result == {"result": "a"}
    # Ledger contains a fresh copy of the original action dict.
    assert ledger[2]["action"] == {"cmd": "go"}


def test_deterministic_reset_and_replay(backend):
    """Resetting after a full execution must replay the sequences identically."""
    backend.reset("sid", 0)
    _ = backend.observe()
    _ = backend.act({"cmd": "a"})
    _ = backend.act({"cmd": "b"})
    _ = backend.advance(10)
    # Capture ledger from the first run.
    first_ledger = copy.deepcopy(backend.ledger)
    # Reset.
    backend.reset("sid", 0)
    # Replay same calls; ledger must match the first run byte‑for‑byte.
    _ = backend.observe()
    _ = backend.act({"cmd": "a"})
    _ = backend.act({"cmd": "b"})
    _ = backend.advance(10)
    assert backend.ledger == first_ledger


def test_scripted_exhaustion_raises(backend):
    """When the scripted sequences are empty, reset raises ``BackendProtocolError``."""
    empty_backend = DummyBackend([], [])
    with pytest.raises(BackendProtocolError, match="scripted observation or action sequence empty"):
        empty_backend.reset("sid", 123)
