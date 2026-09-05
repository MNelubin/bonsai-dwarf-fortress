"""Tests for controller invocation (jsonl-v1 bridge). Uses tiny mock controller
scripts so no agent repo / live DF is needed."""

import sys

from bonsai_lab_agent.controller_invoke import make_controller_fn

MOCK_SINGLE = (
    "import sys, json\n"
    "json.loads(sys.stdin.readline())\n"
    "print(json.dumps({'action': {'command': 'create_stockpile', 'args': [5]}}))\n"
)
MOCK_LIST = (
    "import sys, json\n"
    "json.loads(sys.stdin.readline())\n"
    "print(json.dumps({'action': ["
    "{'command': 'set_labor', 'args': ['MINE', True]},"
    "{'command': 'designate_dig', 'args': [30]}]}))\n"
)
MOCK_NULL = (
    "import sys, json\n"
    "json.loads(sys.stdin.readline())\n"
    "print(json.dumps({'action': None}))\n"
)
MOCK_CRASH = "import sys\nsys.exit(2)\n"


def _script(tmp_path, body):
    p = tmp_path / "controller.py"
    p.write_text(body)
    return p


def test_single_action(tmp_path):
    s = _script(tmp_path, MOCK_SINGLE)
    fn = make_controller_fn([sys.executable, str(s)], str(tmp_path))
    assert fn({"cur_tick": 0}) == [{"command": "create_stockpile", "args": [5]}]


def test_list_action(tmp_path):
    s = _script(tmp_path, MOCK_LIST)
    fn = make_controller_fn([sys.executable, str(s)], str(tmp_path))
    acts = fn({"cur_tick": 0})
    assert len(acts) == 2 and acts[0]["command"] == "set_labor"


def test_null_action_is_empty(tmp_path):
    s = _script(tmp_path, MOCK_NULL)
    fn = make_controller_fn([sys.executable, str(s)], str(tmp_path))
    assert fn({"cur_tick": 0}) == []


def test_crash_returns_empty(tmp_path):
    s = _script(tmp_path, MOCK_CRASH)
    fn = make_controller_fn([sys.executable, str(s)], str(tmp_path))
    assert fn({"cur_tick": 0}) == []


def test_end_to_end_with_scorer(tmp_path, monkeypatch):
    """The controller's intents flow through sanitize -> score. Mock the episode so
    no DF is needed; assert the controller path is exercised and produces a score."""
    from bonsai_lab_agent import game_scorer, stepped_episode
    from bonsai_lab_agent.scoring import EpisodeObs, raw_components

    s = _script(tmp_path, MOCK_LIST)
    cfn = make_controller_fn([sys.executable, str(s)], str(tmp_path))
    T0 = game_scorer.PINNED_T0
    good_h = EpisodeObs(abs_tick=2052801, cohort_alive=7, cohort_size=7, hunger_sum=70000,
                        thirst_sum=50000, stress_danger=0, food_count=30, drink_count=30,
                        buildings=6, dug_tiles=150, workorders_done=15)
    seen = {}

    def fake_ep(controller_fn, **kw):
        seen["actions"] = controller_fn(T0.__dict__)   # exercise the real controller
        return T0, good_h

    monkeypatch.setattr(stepped_episode, "run_stepped_episode", fake_ep)
    ref = raw_components(good_h, T0, 36000)["composite"]
    res = game_scorer.score_submission(cfn, horizon_ticks=36000, k=3,
                                       noop_composite=0.26786, ref_composite=ref)
    assert [a["command"] for a in seen["actions"]] == ["set_labor", "designate_dig"]
    assert res["score"] == 1.0 and res["summary"]["trustworthy"]


def test_controller_host_accepts_a_list_of_actions():
    # It accepted one dict or null only, so every stepped policy - all four reference
    # tiers return lists - got {"error": "TypeError: ..."} back on every round. The fort
    # was never told to do anything and the episode scored the no-op floor, silently.
    import io
    import json

    from bonsai_lab_agent import controller_host

    observation = json.dumps({"type": "observation", "observation": {"round": 0}})

    def multi(obs):
        return [{"command": "set_labor", "args": ["MINE", True]},
                {"command": "designate_dig", "args": [80]}]

    out = io.StringIO()
    old_stdin, old_stdout = controller_host.sys.stdin, controller_host.sys.stdout
    controller_host.sys.stdin = io.StringIO(observation + "\n")
    controller_host.sys.stdout = out
    try:
        controller_host.serve(multi)
    finally:
        controller_host.sys.stdin, controller_host.sys.stdout = old_stdin, old_stdout

    response = json.loads(out.getvalue().strip())
    assert "error" not in response, response
    assert isinstance(response["action"], list)
    assert len(response["action"]) == 2
    assert response["action"][0]["command"] == "set_labor"


def test_controller_host_still_takes_one_action_or_null():
    import io
    import json

    from bonsai_lab_agent import controller_host

    lines = "\n".join(
        json.dumps({"type": "observation", "observation": {"round": r}}) for r in (0, 1)
    ) + "\n"
    answers = iter([{"command": "advance"}, None])

    out = io.StringIO()
    old_stdin, old_stdout = controller_host.sys.stdin, controller_host.sys.stdout
    controller_host.sys.stdin = io.StringIO(lines)
    controller_host.sys.stdout = out
    try:
        controller_host.serve(lambda obs: next(answers))
    finally:
        controller_host.sys.stdin, controller_host.sys.stdout = old_stdin, old_stdout

    first, second = [json.loads(line) for line in out.getvalue().strip().splitlines()]
    assert first["action"] == {"command": "advance"}
    assert second["action"] is None


def test_controller_host_rejects_a_list_of_non_objects():
    import io
    import json

    from bonsai_lab_agent import controller_host

    out = io.StringIO()
    old_stdin, old_stdout = controller_host.sys.stdin, controller_host.sys.stdout
    controller_host.sys.stdin = io.StringIO(
        json.dumps({"type": "observation", "observation": {}}) + "\n")
    controller_host.sys.stdout = out
    try:
        controller_host.serve(lambda obs: ["advance", 7])
    finally:
        controller_host.sys.stdin, controller_host.sys.stdout = old_stdin, old_stdout

    assert "error" in json.loads(out.getvalue().strip())
