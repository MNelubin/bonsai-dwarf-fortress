"""Tests for the map-track capture driver. The DFHack side is faked (it writes the
scratch file the way the Lua script does), so the fold-into-recording logic, the
keyframe cadence, and the failure containment are all exercised without a live fort."""

import json

import pytest

from bonsai_lab_agent.map_recorder import MapRecorder


class FakeSession:
    """Stands in for DFSession + bonsai-map-capture.lua."""

    def __init__(self, capture_file, args_file, *, ok=True, write_line=True,
                 payload_bytes=100):
        self.capture_file = capture_file
        self.args_file = args_file
        self.ok = ok
        self.write_line = write_line
        self.payload_bytes = payload_bytes
        self.modes = []
        self.calls = 0

    def run(self, script, timeout=None):
        assert script == "bonsai-map-capture"
        self.calls += 1
        mode = open(self.args_file).read().splitlines()[0]
        self.modes.append(mode)
        if not self.ok:
            return "MAPCAP ok=0 reason=no_anchor"
        if self.write_line:
            ev = {"kind": mode, "tick": 2016801 + self.calls,
                  "origin": [64, 64, 47], "dims": [64, 64, 5],
                  "pad": "x" * self.payload_bytes,
                  "units": [[1545, 96, 91, 49, 0, 51, 0]], "blds": [], "items": []}
            with open(self.capture_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        return f"MAPCAP ok=1 bytes=123 kind={mode} tiles=25600 changed=4"


@pytest.fixture
def paths(tmp_path):
    return str(tmp_path / "cap.jsonl"), str(tmp_path / "args.txt")


def _mk(paths, **kw):
    cap, args = paths
    sess = FakeSession(cap, args, **{k: v for k, v in kw.items()
                                     if k in {"ok", "write_line", "payload_bytes"}})
    rec = MapRecorder(sess, capture_file=cap, args_file=args,
                      **{k: v for k, v in kw.items()
                         if k in {"keyframe_every", "max_bytes"}})
    return sess, rec


def test_first_snapshot_is_a_keyframe_then_deltas(paths):
    sess, rec = _mk(paths, keyframe_every=4)
    for i in range(6):
        assert rec.snapshot(2016801 + i * 100) is not None
    assert sess.modes == ["kf", "d", "d", "d", "kf", "d"]


def test_explicit_keyframe_request_wins(paths):
    sess, rec = _mk(paths, keyframe_every=100)
    rec.snapshot(1)
    rec.snapshot(2)
    rec.snapshot(3, keyframe=True)
    assert sess.modes == ["kf", "d", "kf"]


def test_each_call_returns_only_its_own_snapshot(paths):
    """The scratch file accumulates across the episode; a snapshot must not re-report
    earlier lines or the recording would balloon with duplicates."""
    sess, rec = _mk(paths)
    a = rec.snapshot(100)
    b = rec.snapshot(200)
    c = rec.snapshot(300)
    assert [a["tick"], b["tick"], c["tick"]] == [2016802, 2016803, 2016804]


def test_refused_capture_returns_none_and_is_logged(paths):
    sess, rec = _mk(paths, ok=False)
    assert rec.snapshot(100) is None
    assert rec.n == 0
    assert any("refused" in e for e in rec.errors)


def test_capture_that_writes_no_line_is_survivable(paths):
    sess, rec = _mk(paths, write_line=False)
    assert rec.snapshot(100) is None
    assert any("no line" in e for e in rec.errors)


def test_rpc_failure_is_contained(paths):
    cap, args = paths

    class Dying:
        def run(self, *a, **k):
            raise RuntimeError("dfhack went away")

    rec = MapRecorder(Dying(), capture_file=cap, args_file=args)
    assert rec.snapshot(100) is None
    assert any("dfhack went away" in e for e in rec.errors)


def test_size_cap_stops_the_map_track_only(paths):
    """A pathological fort must not fill the disk — but stopping the map track must be
    a clean stop, not an episode failure."""
    sess, rec = _mk(paths, payload_bytes=2000, max_bytes=5000)
    got = [rec.snapshot(i) for i in range(6)]
    assert got[0] is not None
    assert rec.truncated
    assert got[-1] is None
    assert any("map track stopped" in e for e in rec.errors)
    n_before_stop = sum(1 for g in got if g is not None)
    assert 1 <= n_before_stop < 6


def test_unparsable_snapshot_is_reported(paths):
    cap, args = paths
    sess = FakeSession(cap, args)

    class Garbling(FakeSession):
        def run(self, script, timeout=None):
            with open(self.capture_file, "a", encoding="utf-8") as f:
                f.write("{not json\n")
            return "MAPCAP ok=1 bytes=1 kind=kf"

    rec = MapRecorder(Garbling(cap, args), capture_file=cap, args_file=args)
    assert rec.snapshot(1) is None
    assert any("unparsable" in e for e in rec.errors)


def test_close_removes_scratch_files(paths):
    import os
    cap, args = paths
    sess, rec = _mk(paths)
    rec.snapshot(1)
    assert os.path.exists(cap)
    rec.close()
    assert not os.path.exists(cap) and not os.path.exists(args)


def test_stats_report_what_happened(paths):
    sess, rec = _mk(paths)
    for i in range(3):
        rec.snapshot(i)
    s = rec.stats()
    assert s["snapshots"] == 3 and s["bytes"] > 0 and not s["truncated"]


def test_folds_into_an_episode_recording(tmp_path, paths):
    """End to end: map events land in the same .rec file as decisions and metrics."""
    from bonsai_lab_agent import recorder as rec_mod
    from bonsai_lab_agent import stepped_episode as se
    from tests.test_stepped_episode import FakeSession as FakeDF

    cap, args = paths
    sess, mrec = _mk(paths, keyframe_every=3)
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec_mod.EpisodeRecorder(path, map_recorder=mrec)
    se.run_stepped_episode(lambda o: [], horizon_ticks=900, rounds=3,
                           session=FakeDF(), recorder=r)
    r.close()

    events = rec_mod.read_recording(path)
    maps = [e for e in events if e["kind"] == "map"]
    assert len(maps) == 4                      # t0 + 3 rounds
    assert maps[0]["keyframe"] is True
    assert maps[0]["dims"] == [64, 64, 5]      # payload survives the fold, flat
    assert {e["kind"] for e in events} == {"meta", "stat", "round", "map", "end"}


def test_a_delta_promoted_to_a_keyframe_is_recorded_as_a_keyframe(tmp_path, paths):
    """The Lua side promotes a delta to a keyframe whenever the fort's bbox grows. A
    viewer that trusted the REQUEST would try to apply a keyframe as a diff, so the
    recording must report what actually came back."""
    from bonsai_lab_agent import recorder as rec_mod
    from bonsai_lab_agent import stepped_episode as se
    from tests.test_stepped_episode import FakeSession as FakeDF

    cap, args = paths

    class Promoting(FakeSession):
        def run(self, script, timeout=None):
            open(self.args_file).read()          # requested mode ignored on purpose
            self.calls += 1
            with open(self.capture_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": "kf", "tick": self.calls,
                                    "dims": [64, 64, 5], "units": []}) + "\n")
            return "MAPCAP ok=1 bytes=1 kind=kf"

    mrec = MapRecorder(Promoting(cap, args), capture_file=cap, args_file=args,
                       keyframe_every=100)     # would ask for deltas after the first
    path = str(tmp_path / "ep.rec.jsonl.gz")
    r = rec_mod.EpisodeRecorder(path, map_recorder=mrec)
    se.run_stepped_episode(lambda o: [], horizon_ticks=600, rounds=2,
                           session=FakeDF(), recorder=r)
    r.close()

    maps = [e for e in rec_mod.read_recording(path) if e["kind"] == "map"]
    assert [e["keyframe"] for e in maps] == [True, True, True]
    assert [e["requested_keyframe"] for e in maps] == [True, False, False]
