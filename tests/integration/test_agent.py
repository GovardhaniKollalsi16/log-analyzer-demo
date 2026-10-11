"""M11: the agent loop with scripted fake LLMs, end to end on the real tools (no API key)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from investigator.agent.fake import ScriptedInvestigator
from investigator.agent.loop import MAX_REPORT_ATTEMPTS, run_agent
from mocklogs import cli as mock_cli, sso
from mocklogs.scenarios import SCENARIOS

from test_planner import SKILL

BIN = Path(sys.executable).parent
EXPECTED = {"upstream-timeout": "HIGH", "db-config": "HIGH", "consumer-processing": "HIGH", "ambiguous": "INSUFFICIENT"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    monkeypatch.setenv("PATH", f"{BIN}{os.pathsep}{os.environ['PATH']}")
    sso.login()

    def make(scenario="upstream-timeout", knobs=None):
        monkeypatch.setenv("MOCKLOGS_SCENARIO", scenario)
        if knobs:
            monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs))
        incident = tmp_path / f"{scenario}-incident.txt"
        incident.write_text("\n".join(mock_cli.run(["scenario", "incident"]).out))
        return incident
    return make


def agent(tmp_path, incident, fake, label="t", max_turns=40):
    # The workdir path is visible to the model, so it must never contain the scenario name (R20).
    # The label only names the transcript file, which the model never sees.
    workdir = tmp_path / f"case-{abs(hash(label)) % 10_000}"
    return run_agent(fake, incident, workdir, SKILL, tmp_path / "runs", label, max_turns=max_turns)


def workdir_of(result):
    return Path(next(e for e in transcript(result) if e["type"] == "start")["workdir"])


def transcript(result):
    return [json.loads(l) for l in result.transcript.read_text().splitlines()]


def tool_results(result, name):
    return [e["result"] for e in transcript(result) if e["type"] == "tool_result" and e["name"] == name]


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_well_behaved_agent_reaches_a_valid_report_on_every_scenario(tmp_path, setup, scenario):
    result = agent(tmp_path, setup(scenario), ScriptedInvestigator(), label=scenario)
    assert result.valid and not result.fell_back and result.report_attempts == 1
    assert result.report["confidence"]["level"] == EXPECTED[scenario]
    work = workdir_of(result)
    assert (work / "report.json").exists() and (work / "report.md").read_text().startswith("# Incident report")
    actions = [json.loads(l) for l in (work / "actions.jsonl").read_text().splitlines()]
    assert actions and all(a["reason"] for a in actions)  # every fetch carries the AI's reason


def test_transcript_records_the_whole_run(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator())
    kinds = [e["type"] for e in transcript(result)]
    assert kinds[0] == "start" and kinds[1] == "user" and kinds[-1] == "final"
    assert {"assistant", "tool_result"} <= set(kinds)
    final = transcript(result)[-1]
    assert final["valid"] is True and final["report"]["confidence"]["level"] == "HIGH"
    assert result.transcript.name.endswith("-t.jsonl")


def test_agent_may_investigate_beyond_the_suggestions(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator(extra_fetch=True))
    actions = [json.loads(l) for l in (workdir_of(result) / "actions.jsonl").read_text().splitlines()]
    extra = [a for a in actions if a["reason"].startswith("widen the window")]
    assert len(extra) == 1 and extra[0]["allowed"] is True and extra[0]["exit_code"] == 0
    assert result.valid


def test_a_forbidden_command_is_denied_and_the_investigation_continues(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator(try_forbidden=True))
    denied = [r for r in tool_results(result, "run") if r.get("allowed") is False]
    assert len(denied) == 1 and denied[0]["reasons"][0]["code"] == "app_not_related"
    assert result.valid and result.report["confidence"]["level"] == "HIGH"


def test_agent_proposing_its_own_cause_cannot_overclaim(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator(own_cause=True))
    submissions = tool_results(result, "submit_report")
    assert submissions[0]["accepted"] is False
    assert {e["code"] for e in submissions[0]["errors"]} & {"confidence_above_ceiling", "insufficient_with_cause"}
    assert result.valid and not result.fell_back
    rc = result.report["root_cause"]
    assert rc == "unknown" or rc["source"] == "ai"  # its own pick, at an honest level, or an honest unknown
    assert result.report["confidence"]["level"] != "HIGH"


def test_an_invented_event_id_is_rejected_then_fixed(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator(bogus_first=True))
    submissions = tool_results(result, "submit_report")
    assert [s["accepted"] for s in submissions] == [False, True]
    assert submissions[0]["errors"][0]["code"] == "unknown_event_id"
    assert result.valid and result.report_attempts == 2


def test_three_invalid_reports_fall_back_to_insufficient(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator(never_valid=True))
    assert result.report_attempts == MAX_REPORT_ATTEMPTS and result.fell_back
    assert result.report["confidence"]["level"] == "INSUFFICIENT" and result.report["root_cause"] == "unknown"
    assert result.valid  # the fallback itself is a valid report
    assert "failed validation 3 times" in result.fallback_reason


def test_turn_budget_exhaustion_falls_back(tmp_path, setup):
    result = agent(tmp_path, setup(), ScriptedInvestigator(loop_forever=True), max_turns=5)
    assert result.turns == 5 and result.fell_back and "turn budget" in result.fallback_reason
    assert result.report["confidence"]["level"] == "INSUFFICIENT"


def test_runs_are_append_only_and_never_deleted(tmp_path, setup):
    incident = setup()
    keep = tmp_path / "runs" / "20000101T000000000000Z-older-run.jsonl"
    keep.parent.mkdir(parents=True)
    keep.write_text('{"type": "start"}\n')
    a = agent(tmp_path, incident, ScriptedInvestigator(), label="one")
    b = agent(tmp_path, incident, ScriptedInvestigator(), label="two")
    assert keep.exists() and a.transcript != b.transcript
    assert len(list((tmp_path / "runs").glob("*.jsonl"))) == 3


def test_cli_agent(tmp_path, setup, monkeypatch, capsys):
    from investigator import cli as investigator_cli
    incident = setup()
    monkeypatch.chdir(SKILL.parents[3])
    code = investigator_cli.main(["agent", "--workdir", str(tmp_path / "case-cli"), "--incident-file", str(incident),
                                  "--runs-dir", str(tmp_path / "runs"), "--label", "cli"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["valid"] is True and out["confidence"] == "HIGH"
    with pytest.raises(SystemExit) as exc:  # no API-key provider exists (D32)
        investigator_cli.main(["agent", "--workdir", str(tmp_path / "x"), "--incident-file", str(incident),
                               "--provider", "anthropic"])
    assert exc.value.code == 2


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_model_never_sees_the_scenario_name(tmp_path, setup, scenario):
    """R20 for the agent path: nothing the model receives (first message, tool results) names the scenario."""
    result = agent(tmp_path, setup(scenario), ScriptedInvestigator(extra_fetch=True), label=scenario)
    visible = [json.dumps(e) for e in transcript(result) if e["type"] in ("user", "tool_result")]
    assert visible and not any(scenario in v for v in visible)
