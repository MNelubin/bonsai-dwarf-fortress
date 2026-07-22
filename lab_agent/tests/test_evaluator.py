from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bonsai_lab_agent.evaluator import (
    controller_command,
    evaluation_outcome,
    fixture_observations,
    run_controller,
    tagged_json,
)


def test_python_callable_controller_obeys_jsonl_contract(tmp_path):
    (tmp_path / "policy.py").write_text(
        "def decide(observation):\n"
        "    return {'command': 'pause'} if not observation.get('paused') else None\n",
        encoding="utf-8",
    )
    command = controller_command(
        tmp_path,
        {"kind": "python_callable", "entrypoint": "policy:decide"},
    )
    responses, latency, stderr = run_controller(
        command, tmp_path, fixture_observations(), timeout_seconds=10
    )
    assert len(responses) == 4
    assert responses[1] == responses[3]
    assert responses[1]["action"] == {"command": "pause"}
    assert latency >= 0
    assert stderr == ""


def test_arbitrary_command_controller_is_supported(tmp_path):
    script = tmp_path / "controller.py"
    script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        " print(json.dumps({'action': {'command': 'observe'}}), flush=True)\n",
        encoding="utf-8",
    )
    command = controller_command(tmp_path, {"kind": "command", "argv": [sys.executable, str(script)]})
    responses, _, _ = run_controller(command, tmp_path, fixture_observations()[:2], 10)
    assert [response["action"]["command"] for response in responses] == ["observe", "observe"]


def test_invalid_command_manifest_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="argv"):
        controller_command(tmp_path, {"kind": "command", "argv": []})


def test_dfhack_state_script_is_packaged_and_emits_a_versioned_marker():
    script = (
        Path(__file__).parents[1] / "bonsai_lab_agent" / "dfhack" / "bonsai-eval-state.lua"
    ).read_text(encoding="utf-8")
    assert "BONSAI_GAME_STATE" in script
    assert "bonsai-game-state-v1" in script
    assert "df.global.cur_year_tick" in script


def test_tagged_json_accepts_ansi_prefixed_pretty_dfhack_output():
    output = (
        "\x1b[0mBONSAI_GAME_STATE {\n"
        '  "schema": "bonsai-game-state-v1",\n'
        '  "ok": true,\n'
        '  "year": 0,\n'
        '  "tick": 0\n'
        "}\n\x1b[0m\n"
        'BONSAI_PROBE_RESULT {"exit":0,"runtime_ready":true}\n'
    )

    state = tagged_json(output, "BONSAI_GAME_STATE ")
    marker = tagged_json(output, "BONSAI_PROBE_RESULT ")

    assert state == {
        "schema": "bonsai-game-state-v1",
        "ok": True,
        "year": 0,
        "tick": 0,
    }
    assert marker == {"exit": 0, "runtime_ready": True}


def test_tagged_json_returns_none_for_missing_or_truncated_marker():
    assert tagged_json("unrelated", "BONSAI_GAME_STATE ") is None
    assert tagged_json("BONSAI_GAME_STATE {", "BONSAI_GAME_STATE ") is None


def test_api_failure_cannot_receive_a_passing_score():
    score, verdict, failure_kind = evaluation_outcome(True, True, False)
    assert score == pytest.approx(0.6)
    assert verdict == "game_api_failed"
    assert failure_kind == "game_api"


def test_live_deterministic_controller_passes_api_smoke():
    assert evaluation_outcome(True, True, True) == (1.0, "api_smoke_passed", None)
