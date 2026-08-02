"""Tests for the DF session transport.

session.py had no tests at all, which is how a file that did not even parse reached a
commit. Everything here runs against a fake subprocess layer — no DF, no DFHack — and
covers the properties that parallel episodes depend on and that fail SILENTLY when
broken: an episode that boots on the wrong port still boots, and only shows up as two
forts fighting over one save.
"""

import subprocess

import pytest

from bonsai_lab_agent import session as S


class FakeRun:
    """Records every subprocess.run call and replies from a scripted queue."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = list(replies or [])
        self.default = "42 true"

    def __call__(self, argv, **kw):
        self.calls.append({"argv": argv, "env": kw.get("env") or {},
                           "cwd": kw.get("cwd"), "timeout": kw.get("timeout")})
        out = self.replies.pop(0) if self.replies else self.default
        if isinstance(out, Exception):
            raise out
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


@pytest.fixture
def fake(monkeypatch):
    f = FakeRun()
    monkeypatch.setattr(S.subprocess, "run", f)
    monkeypatch.setattr(S.time, "sleep", lambda *_: None)
    return f


def test_scratch_paths_are_per_port():
    """Two parallel episodes in one DF directory must not share an actions file."""
    a, b = S.DFSession(port=5001), S.DFSession(port=5007)
    assert a.actions_file != b.actions_file
    assert a.capture_file != b.capture_file
    assert "5007" in b.actions_file and "5007" in b.capture_file


def test_env_carries_both_port_variables(fake):
    """bonsai_session.sh boots on BONSAI_EPISODE_PORT; dfhack-run dials DFHACK_PORT.

    Exporting only DFHACK_PORT booted every episode on the script's default 5001 and made
    close() kill that fort rather than its own.
    """
    s = S.DFSession(port=5004)
    s.run("bonsai-observe")
    env = fake.calls[-1]["env"]
    assert env["DFHACK_PORT"] == "5004"
    assert env["BONSAI_EPISODE_PORT"] == "5004"


def test_boot_passes_port_through_to_the_shell(fake):
    fake.replies = ["READY port=5004 tick=16801 frame=0", "123"]
    s = S.DFSession(port=5004)
    s.boot()
    boot_call = fake.calls[0]
    assert boot_call["argv"][:3] == ["bash", S.SESSION_SH, "boot"]
    assert boot_call["env"]["BONSAI_EPISODE_PORT"] == "5004"
    assert s.booted and s.boot_frame == 123


def test_boot_without_ready_raises(fake):
    fake.replies = ["LOADFAIL:savelist"]
    with pytest.raises(S.SessionError, match="boot failed"):
        S.DFSession().boot()


def test_boot_retries_a_blank_first_frame(fake):
    """READY only means the load finished; the first RPC after it can come back empty."""
    fake.replies = ["READY port=5001", "", "", "777"]
    s = S.DFSession()
    s.boot()
    assert s.boot_frame == 777


def test_advance_sends_the_tick_count_as_an_argument(fake):
    """A shared advance_n.txt let one parallel fort read another's horizon."""
    fake.replies = ["100", "ADVANCING", "1100 true"]
    s = S.DFSession()
    assert s.advance(1000) == 1100
    adv = [c for c in fake.calls if "bonsai-advance2" in c["argv"]][0]
    assert adv["argv"][-1] == "1000"


def test_advance_waits_for_both_the_target_and_the_pause(fake):
    """Reaching the tick target mid-run is not enough — the fort must have stopped."""
    fake.replies = ["100", "ADV", "1100 false", "1100 false", "1100 true"]
    s = S.DFSession()
    assert s.advance(1000) == 1100


def test_advance_of_nothing_does_not_call_the_engine(fake):
    fake.replies = ["55"]
    assert S.DFSession().advance(0) == 55
    assert not [c for c in fake.calls if "bonsai-advance2" in c["argv"]]


def test_advance_that_never_arrives_raises(fake, monkeypatch):
    clock = iter([0, 0, 1, 2, 1e6, 1e6])
    monkeypatch.setattr(S.time, "time", lambda: next(clock))
    fake.replies = ["100", "ADV", "100 false", "100"]
    with pytest.raises(S.SessionError, match="advance stalled"):
        S.DFSession().advance(1000)


def test_frame_and_paused_retries_a_blank_reply(fake):
    """DFHack occasionally answers with nothing; one blank used to end the episode."""
    fake.replies = ["", "  ", "900 true"]
    assert S.DFSession().frame_and_paused() == (900, True)


def test_frame_and_paused_gives_up_loudly(fake):
    fake.replies = ["", "", "", ""]
    with pytest.raises(S.SessionError, match="bad frame/pause reply"):
        S.DFSession().frame_and_paused()


def test_rpc_timeout_becomes_a_session_error(fake):
    fake.replies = [subprocess.TimeoutExpired("dfhack-run", 25)]
    with pytest.raises(S.SessionError, match="timed out"):
        S.DFSession().run("bonsai-observe")


def test_observe_parses_the_obs_line(fake):
    fake.replies = ["noise\nOBS nsolid=100 nhostile=2 warn=none\ntail"]
    got = S.DFSession().observe()
    assert got["nsolid"] == "100" and got["nhostile"] == "2"


def test_observe_without_an_obs_line_raises(fake):
    fake.replies = ["nothing useful here"]
    with pytest.raises(S.SessionError, match="no OBS line"):
        S.DFSession().observe()


def test_apply_actions_writes_tab_separated_intents(tmp_path, fake):
    s = S.DFSession()
    s.actions_file = str(tmp_path / "acts.txt")
    s.apply_actions([{"verb": "designate_dig", "args": [25]},
                     {"verb": "set_labor", "args": {"labor": "MINE", "on": True}},
                     {"verb": "advance"}])
    assert open(s.actions_file).read().splitlines() == [
        "designate_dig\t25", "set_labor\tMINE\tTrue", "advance"]
    assert fake.calls[-1]["argv"][-1] == s.actions_file


def test_close_is_idempotent_and_only_kills_when_booted(fake):
    s = S.DFSession(port=5006)
    s.close()
    assert not fake.calls                      # never booted: nothing to kill
    s.booted = True
    s.close()
    s.close()
    kills = [c for c in fake.calls if c["argv"][-1] == "kill"]
    assert len(kills) == 1
    assert kills[0]["env"]["BONSAI_EPISODE_PORT"] == "5006"


def test_close_survives_a_kill_that_hangs(fake):
    fake.replies = [subprocess.TimeoutExpired("bash", 60)]
    s = S.DFSession()
    s.booted = True
    s.close()                                  # must not raise out of a finally block
    assert not s.booted


def test_context_manager_kills_even_when_the_episode_raises(fake):
    fake.replies = ["READY", "1"]
    with pytest.raises(ValueError):
        with S.DFSession(port=5005):
            raise ValueError("episode blew up")
    assert [c for c in fake.calls if c["argv"][-1] == "kill"]


def test_ansi_colour_is_stripped(fake):
    fake.replies = ["\x1b[32mOBS nsolid=7\x1b[0m"]
    assert S.DFSession().observe()["nsolid"] == "7"
