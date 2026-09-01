"""Tests for the episode recorder. Exercises the real gzip file end to end — the
recorder's job is to produce a file someone can actually read later, so writing a real
one and reading it back is the test that matters."""

import gzip
import json

import pytest

from bonsai_lab_agent import recorder as rec
from bonsai_lab_agent import stepped_episode as se
from bonsai_lab_agent.scoring import EpisodeObs

from tests.test_stepped_episode import FakeSession


def _obs(tick=2016801, alive=7, buildings=1):
    return EpisodeObs(abs_tick=tick, cohort_alive=alive, cohort_size=7,
                      hunger_sum=100, thirst_sum=80, stress_danger=0,
                      food_count=12, drink_count=12, buildings=buildings,
                      dug_tiles=0, workorders_done=0)


def test_records_a_full_episode_and_reads_back(tmp_path):
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path, meta={"episode_id": "e1", "regime_key": "abc"})
    s = FakeSession()
    se.run_stepped_episode(
        lambda o: [{"command": "create_stockpile", "args": [5]}],
        horizon_ticks=1200, rounds=4, session=s, recorder=r)

    events = rec.read_recording(path)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "end"
    assert kinds.count("round") == 4
    assert kinds.count("stat") == 4 + 2          # per round + t0 + horizon
    meta = events[0]
    assert meta["v"] == rec.FORMAT_VERSION
    assert meta["horizon_ticks"] == 1200 and meta["rounds"] == 4
    assert meta["episode_id"] == "e1" and meta["regime_key"] == "abc"


def test_decision_track_shows_what_was_allowed_and_what_was_dropped(tmp_path):
    """This is the layer the owner cares about most — it must show the agent's
    reasoning surface, including the intents the anti-forgery gate refused."""
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)
    se.run_stepped_episode(
        lambda o: [{"command": "create_stockpile", "args": [5]},
                   {"command": "launch_missiles", "args": ["now"]},
                   {"command": "advance"},
                   "definitely not an action"],
        horizon_ticks=600, rounds=2, session=FakeSession(), recorder=r)

    rounds = [e for e in rec.read_recording(path) if e["kind"] == "round"]
    assert len(rounds) == 2
    r0 = rounds[0]
    assert r0["dispatched"] == ["create_stockpile"]          # `advance` is not dispatched
    reasons = sorted(d["reason"] for d in r0["dropped"])
    # The reason is the gate's own sentence, not a category. "not_allow_listed" covered
    # an unknown verb and a missing argument alike, so a replay could not show which
    # mistake the agent kept repeating.
    assert len(reasons) == 2
    assert any("launch_missiles" in s and "not an action" in s for s in reasons)
    assert any("str" in s or "not an object" in s for s in reasons)
    assert any(d.get("verb") == "launch_missiles" for d in r0["dropped"])
    assert any("launch_missiles" in s and "not an action" in s
               for s in r0["gate_messages"])
    assert len(r0["intents"]) == 4                            # the raw ask is preserved


def test_metric_track_follows_the_fort(tmp_path):
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)
    se.run_stepped_episode(lambda o: [{"command": "create_stockpile", "args": [1]}],
                           horizon_ticks=1200, rounds=4, session=FakeSession(), recorder=r)
    stats = [e for e in rec.read_recording(path) if e["kind"] == "stat"]
    posts = [e for e in stats if e["phase"] == "post"]
    assert [e["buildings"] for e in posts] == [2, 3, 4, 5]     # grew every round
    assert [e["i"] for e in posts] == [0, 1, 2, 3]
    assert stats[0]["phase"] == "t0" and stats[-1]["phase"] == "horizon"


def test_decision_track_records_dependency_snapshots(tmp_path):
    class Resources(FakeSession):
        def observe(self):
            raw = super().observe()
            raw.update({
                "nwood": "7", "nboulder": "2", "nworkshop": "1",
                "nbuiltshop": "1", "nunbuiltshop": "0", "shops": "Carpenters:1",
                "pending_shops": "Carpenters:0",
                "nfarmplots": "2",
                "njobs": "3", "nunassignedjobs": "2", "nmanagerjobs": "1",
                "nbrewjobs": "0",
                "norders": "1", "norderleft": "4",
            })
            return raw

    path = str(tmp_path / "dependencies.rec.jsonl.gz")
    recorder = rec.EpisodeRecorder(path)
    se.run_stepped_episode(lambda obs: [], horizon_ticks=300, rounds=1,
                           session=Resources(), recorder=recorder)
    event = next(e for e in rec.read_recording(path) if e["kind"] == "round")
    assert event["dependencies"]["resources"]["wood"] == 7
    assert event["dependencies"]["workshops"]["built_by_type"] == {"Carpenters": 1}
    assert event["post_dependencies"]["manager_orders"]["amount_left"] == 4
    assert event["post_dependencies"]["food_chain"]["farm_plots"] == 2


def test_controller_error_is_recorded_not_hidden(tmp_path):
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)

    def boom(o):
        raise ValueError("agent exploded")

    se.run_stepped_episode(boom, horizon_ticks=600, rounds=2,
                           session=FakeSession(), recorder=r)
    rounds = [e for e in rec.read_recording(path) if e["kind"] == "round"]
    assert all("ValueError: agent exploded" in (e["controller_error"] or "") for e in rounds)


def test_recorder_never_breaks_an_episode(tmp_path):
    """A recorder failure must cost the recording, never the score."""
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)
    r._fh.close()                       # yank the file handle mid-flight
    s = FakeSession()
    t0, h = se.run_stepped_episode(lambda o: [], horizon_ticks=900, rounds=3,
                                   session=s, recorder=r)
    assert s.advances == [300, 300, 300]
    assert h.abs_tick > t0.abs_tick


def test_exotic_controller_output_is_shrunk_not_dumped(tmp_path):
    """An untrusted controller can return huge/weird objects. The recording must stay
    small and JSON-clean rather than inheriting whatever it produced."""
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)

    class Weird:
        def __repr__(self):
            return "W" * 5000

    se.run_stepped_episode(lambda o: [{"command": "set_labor", "args": [Weird()] * 500}],
                           horizon_ticks=300, rounds=1, session=FakeSession(), recorder=r)
    r.close()
    rounds = [e for e in rec.read_recording(path) if e["kind"] == "round"]
    args = rounds[0]["intents"][0]["args"]
    assert len(args) <= 64                      # list truncated
    assert all(len(a) <= 500 for a in args)     # each value truncated
    assert all(len(message) <= 240 for message in rounds[0]["gate_messages"])


def test_truncated_file_still_reads(tmp_path):
    """A watchdog-killed episode leaves a partial file — exactly when you most want it."""
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)
    se.run_stepped_episode(lambda o: [], horizon_ticks=900, rounds=3,
                           session=FakeSession(), recorder=r)
    raw = gzip.open(path, "rb").read()
    with open(path, "wb") as f:                 # chop the gzip stream mid-way
        f.write(gzip.compress(raw[: int(len(raw) * 0.6)]))
    events = rec.read_recording(path)
    assert len(events) >= 1 and events[0]["kind"] == "meta"


def test_recording_is_small(tmp_path):
    """Always-on means the size has to stay boring."""
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec.EpisodeRecorder(path)
    se.run_stepped_episode(lambda o: [{"command": "set_labor", "args": ["MINE", True]}],
                           horizon_ticks=36000, rounds=24, session=FakeSession(), recorder=r)
    r.close()
    assert r.size_bytes() < 12_000              # a full 30-day episode's decisions+metrics


def test_map_recorder_failure_is_contained(tmp_path):
    path = str(tmp_path / "ep.rec.jsonl.gz")

    class BadMap:
        def snapshot(self, tick, keyframe=False):
            raise RuntimeError("dfhack went away")

        def close(self):
            raise RuntimeError("and again")

    r = rec.EpisodeRecorder(path, map_recorder=BadMap())
    s = FakeSession()
    se.run_stepped_episode(lambda o: [], horizon_ticks=600, rounds=2,
                           session=s, recorder=r)
    assert s.advances == [300, 300]
    assert any("dfhack went away" in e for e in r.errors)


def test_map_events_are_written_when_a_map_recorder_is_present(tmp_path):
    path = str(tmp_path / "ep.rec.jsonl.gz")

    class Map:
        def __init__(self):
            self.calls = []

        def snapshot(self, tick, keyframe=False):
            self.calls.append((tick, keyframe))
            return {"tiles_rle": [[215, 4]], "keyframe": keyframe}

        def close(self):
            pass

    m = Map()
    r = rec.EpisodeRecorder(path, map_recorder=m)
    se.run_stepped_episode(lambda o: [], horizon_ticks=900, rounds=3,
                           session=FakeSession(), recorder=r)
    maps = [e for e in rec.read_recording(path) if e["kind"] == "map"]
    assert len(maps) == 4                       # t0 keyframe + 3 rounds
    assert maps[0]["keyframe"] is True
    assert all(e["keyframe"] is False for e in maps[1:])


@pytest.mark.parametrize("eid,expect", [
    ("sub-123", "sub-123.rec.jsonl.gz"),
    ("a/../../etc/passwd", "a_.._.._etc_passwd.rec.jsonl.gz"),
    ("x" * 300, "x" * 120 + ".rec.jsonl.gz"),
])
def test_recording_path_is_sanitized(eid, expect, tmp_path):
    """episode_id can carry submission-derived text; it must never escape the dir."""
    assert rec.recording_path(eid, str(tmp_path)).endswith(expect)
