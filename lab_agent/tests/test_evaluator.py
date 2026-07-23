from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import pytest

from bonsai_lab_agent.evaluator import (
    EvaluatorConfig,
    controller_command,
    evaluation_outcome,
    fixture_observations,
    prepare_checkout,
    run_controller,
    tagged_json,
)


def test_prepare_checkout_fetches_missing_commit_from_trusted_remote(tmp_path):
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    baseline = tmp_path / "baseline"
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (source / "value.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "value.txt"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "one"], check=True)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "-C", str(source), "push", str(remote), "HEAD:main"], check=True)
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(remote), str(baseline)], check=True)
    (source / "value.txt").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "commit", "-qam", "two"], check=True)
    subprocess.run(["git", "-C", str(source), "push", str(remote), "HEAD:main"], check=True)
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    config = EvaluatorConfig(
        control_url="http://control.invalid",
        lab_token="token",
        baseline_repo=baseline,
        baseline_remote=str(remote),
        runs_dir=tmp_path / "runs",
        poll_seconds=1,
        controller_timeout_seconds=1,
        probe_bin="probe",
        dfhack_run="dfhack-run",
    )

    checkout = prepare_checkout(config, {"id": "job", "base_commit": commit})

    assert subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip() == commit


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
