"""Tests for the long-lived controller process. These spawn REAL subprocesses (a tiny
fake controller written to tmp_path) so the pipe/threading behaviour is genuinely
exercised — the failure modes this module exists to contain are all I/O failure modes,
and a mocked pipe would not reproduce them."""

import json
import sys
import textwrap
import time

import pytest

from bonsai_lab_agent.persistent_controller import (
    PersistentController, _extract_actions, make_persistent_controller_fn,
)


def fake_controller(tmp_path, body: str, name="ctl.py"):
    """Write a controller that runs `body` per stdin line. `body` sees `req` and should
    `print(json.dumps(...), flush=True)`."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(f"""
        import json, os, sys, time
        for _line in sys.stdin:
            req = json.loads(_line)
{textwrap.indent(textwrap.dedent(body), " " * 12)}
    """), encoding="utf-8")
    return [sys.executable, str(p)]


# ------------------------------------------------------------------ the core claim
def test_one_process_answers_many_rounds(tmp_path):
    """The whole point: ~24 rounds per episode must not cost 24 interpreter starts."""
    cmd = fake_controller(tmp_path, """
        print(json.dumps({"action": {"command": "create_stockpile",
                                     "args": [req["step"], os.getpid()]}}), flush=True)
    """)
    with PersistentController(cmd, str(tmp_path)) as ctl:
        pids, steps = set(), []
        for i in range(24):
            acts = ctl.ask({"round": i})
            assert len(acts) == 1
            steps.append(acts[0]["args"][0])
            pids.add(acts[0]["args"][1])
    assert steps == list(range(24))       # every round got its own answer, in order
    assert len(pids) == 1                 # ...from ONE process


def test_controller_sees_each_observation(tmp_path):
    cmd = fake_controller(tmp_path, """
        print(json.dumps({"action": {"command": "set_labor",
                                     "args": [req["observation"]["buildings"]]}}), flush=True)
    """)
    with PersistentController(cmd, str(tmp_path)) as ctl:
        got = [ctl.ask({"buildings": n})[0]["args"][0] for n in (1, 5, 9)]
    assert got == [1, 5, 9]


def test_list_of_intents_is_accepted(tmp_path):
    """A setup-style round may emit a whole plan at once."""
    cmd = fake_controller(tmp_path, """
        print(json.dumps({"action": [{"command": "set_labor"},
                                     {"command": "designate_dig"},
                                     "junk"]}), flush=True)
    """)
    with PersistentController(cmd, str(tmp_path)) as ctl:
        acts = ctl.ask({})
    assert [a["command"] for a in acts] == ["set_labor", "designate_dig"]


# ------------------------------------------------------------------ failure containment
def test_hung_controller_is_abandoned_and_stays_dead(tmp_path):
    """A controller that stops answering must cost its rounds, not the episode. And it
    must NOT be retried every round — that would multiply the stall by the round count."""
    cmd = fake_controller(tmp_path, """
        if req["step"] == 0:
            print(json.dumps({"action": {"command": "set_labor"}}), flush=True)
        else:
            time.sleep(120)
    """)
    ctl = PersistentController(cmd, str(tmp_path), round_timeout=1.0)
    ctl.start()
    try:
        assert len(ctl.ask({})) == 1          # round 0 answers
        t = time.time()
        assert ctl.ask({}) == []              # round 1 hangs -> abandoned
        assert 0.5 < time.time() - t < 10
        t = time.time()
        for _ in range(5):
            assert ctl.ask({}) == []          # later rounds are instant no-ops
        assert time.time() - t < 1.0          # ...not 5 more timeouts
        assert ctl.dead and ctl.failures
    finally:
        ctl.close()


def test_crashing_controller_degrades_to_noop(tmp_path):
    cmd = fake_controller(tmp_path, """
        if req["step"] == 1:
            sys.exit(3)
        print(json.dumps({"action": {"command": "set_labor"}}), flush=True)
    """)
    with PersistentController(cmd, str(tmp_path), round_timeout=5) as ctl:
        assert len(ctl.ask({})) == 1
        assert ctl.ask({}) == []
        assert ctl.ask({}) == []
        assert ctl.dead


def test_controller_that_never_writes_anything(tmp_path):
    cmd = fake_controller(tmp_path, """
        pass
    """)
    with PersistentController(cmd, str(tmp_path), round_timeout=1.0) as ctl:
        assert ctl.ask({}) == []
        assert ctl.dead


def test_chatty_controller_does_not_deadlock(tmp_path):
    """A controller that floods stdout must not fill the pipe and wedge us."""
    cmd = fake_controller(tmp_path, """
        for _ in range(500):
            print(json.dumps({"noise": "x" * 200}), flush=True)
        print(json.dumps({"action": {"command": "set_labor"}}), flush=True)
    """)
    with PersistentController(cmd, str(tmp_path), round_timeout=10) as ctl:
        # first response line is noise (no action) -> no actions this round, but alive
        assert ctl.ask({}) == []
        assert not ctl.dead


def test_unspawnable_command_is_survivable(tmp_path):
    ctl = PersistentController(["/definitely/not/a/binary"], str(tmp_path))
    ctl.start()
    assert ctl.ask({}) == []
    assert ctl.dead and ctl.failures
    ctl.close()


def test_close_is_idempotent(tmp_path):
    cmd = fake_controller(tmp_path, """
        print(json.dumps({"action": None}), flush=True)
    """)
    ctl = PersistentController(cmd, str(tmp_path))
    ctl.start()
    ctl.ask({})
    ctl.close()
    ctl.close()
    assert ctl.ask({}) == []


# ------------------------------------------------------------------ response parsing
@pytest.mark.parametrize("line,expected", [
    ('{"action":{"command":"set_labor"}}', [{"command": "set_labor"}]),
    ('{"action":[{"command":"a"},{"command":"b"}]}', [{"command": "a"}, {"command": "b"}]),
    ('{"action":null}', []),
    ('{"error":"AttributeError: boom"}', []),
    ('{"action":{"command":"x"},"error":"also bad"}', []),   # error wins
    ('not json at all', []),
    ('', []),
    ('[1,2,3]', []),
    ('{"action":"a string"}', []),
])
def test_extract_actions(line, expected):
    assert _extract_actions(line) == expected


def test_make_persistent_controller_fn_returns_usable_pair(tmp_path):
    cmd = fake_controller(tmp_path, """
        print(json.dumps({"action": {"command": "advance"}}), flush=True)
    """)
    fn, handle = make_persistent_controller_fn(cmd, str(tmp_path))
    try:
        assert fn({"round": 0}) == [{"command": "advance"}]
        assert fn({"round": 1}) == [{"command": "advance"}]
        assert handle.stats()["rounds"] == 2
        assert not handle.stats()["dead"]
    finally:
        handle.close()


def test_stepped_driver_accepts_the_persistent_fn(tmp_path):
    """End-to-end shape check: the driver's controller_fn contract is satisfied."""
    from bonsai_lab_agent import stepped_episode as se
    from tests.test_stepped_episode import FakeSession

    cmd = fake_controller(tmp_path, """
        n = req["observation"]["round"]
        print(json.dumps({"action": {"command": "create_stockpile", "args": [1]}
                          if n < 2 else {"command": "advance"}}), flush=True)
    """)
    fn, handle = make_persistent_controller_fn(cmd, str(tmp_path))
    try:
        s = FakeSession()
        t0, h = se.run_stepped_episode(fn, horizon_ticks=1200, rounds=4, session=s)
        assert handle.stats()["rounds"] == 4
        assert len(s.applied) == 2          # only the first two rounds dispatched
        assert h.buildings > t0.buildings
    finally:
        handle.close()
