"""M12: the Claude Code path (D32), run against a fake `claude` executable (no account is used)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from investigator.agent.claude_code import PROJECT_DIR, build_command, run_claude_code
from mocklogs import cli as mock_cli, sso
from mocklogs.scenarios import SCENARIOS

from test_planner import SKILL

BIN = Path(sys.executable).parent
FAKE = Path(__file__).resolve().parents[1] / "fakes" / "fake_claude.py"
EXPECTED = {"upstream-timeout": "HIGH", "db-config": "HIGH", "consumer-processing": "HIGH", "ambiguous": "INSUFFICIENT"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    monkeypatch.setenv("PATH", f"{BIN}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(tmp_path / "record.json"))
    sso.login()
    claude = tmp_path / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    claude.chmod(0o755)

    def make(scenario="upstream-timeout", mode="lead"):
        monkeypatch.setenv("MOCKLOGS_SCENARIO", scenario)
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        incident = tmp_path / f"{scenario}-incident.txt"
        incident.write_text("\n".join(mock_cli.run(["scenario", "incident"]).out))
        return incident, str(claude)
    return make


def run(tmp_path, incident, claude, label="t"):
    workdir = tmp_path / f"case-{abs(hash(label)) % 10_000}"  # neutral: the model sees it (R20)
    return run_claude_code(incident, workdir, SKILL, tmp_path / "runs", label, claude_bin=claude)


def events(result):
    return [json.loads(l) for l in result.transcript.read_text().splitlines()]


def record(tmp_path):
    return json.loads((tmp_path / "record.json").read_text())


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_subagent_report_is_validated_and_kept_on_every_scenario(tmp_path, setup, scenario):
    result = run(tmp_path, *setup(scenario))
    assert result.valid and not result.fell_back
    assert result.report["confidence"]["level"] == EXPECTED[scenario]
    assert result.report_attempts == 1
    workdir = Path(next(e for e in events(result) if e["type"] == "start")["workdir"])
    assert (workdir / "report.md").is_file()
    assert any(e["type"] == "claude_event" for e in events(result))


def test_command_uses_the_login_not_an_api_key_and_only_preapproved_tools(tmp_path, setup, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")
    run(tmp_path, *setup())
    rec = record(tmp_path)
    assert rec["secret_env"] == []
    assert rec["cwd"] == str(PROJECT_DIR)
    argv = rec["argv"]
    assert argv[argv.index("--agent") + 1] == "incident-investigator"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--setting-sources") + 1] == "project"
    allowed = argv[argv.index("--allowedTools") + 1:]
    assert allowed[:-1] == [f"Bash(investigator {c} *)" for c in
                            ("init", "plan", "run", "correlate", "check", "score", "validate", "render")]
    assert allowed[-1].startswith("Edit(//")
    denied = argv[argv.index("--disallowedTools") + 1:argv.index("--allowedTools")]
    assert "Bash(investigator agent *)" in denied
    assert {f"Read(/{PROJECT_DIR / d}/**)" for d in ("src", "tests", "docs", "runs")} <= set(denied)
    hook = json.loads(argv[argv.index("--settings") + 1])["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "Bash" and Path(hook["hooks"][0]["command"]).is_file()
    assert rec["prompt"].splitlines()[0].startswith("workdir: /")


def test_edit_rule_is_scoped_to_the_workdir(tmp_path):
    cmd = build_command("claude", Path("/abs/case-7"), Path("/repo"))
    assert cmd[-1] == "Edit(//abs/case-7/**)"
    assert "Read(//repo/src/**)" in cmd


def test_help_calls_are_not_counted_as_report_attempts():
    from investigator.agent.claude_code import _report_attempts
    use = lambda c: {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                                  "input": {"command": c}}]}}
    assert _report_attempts([use("investigator validate --help"),
                             use("investigator validate --workdir /w --report /w/report.json")]) == 1


def test_blocked_commands_reach_the_model_and_the_run_still_completes(tmp_path, setup):
    result = run(tmp_path, *setup(mode="forbidden"))
    blocked = [b for e in events(result) if e["type"] == "claude_event" and e["event"]["type"] == "user"
               for b in e["event"]["message"]["content"] if b.get("is_error")]
    assert len(blocked) == 3
    assert all("Blocked by the incident-investigator guard" in b["content"] for b in blocked)
    assert result.valid and not result.fell_back


def test_missing_report_falls_back_to_insufficient(tmp_path, setup):
    result = run(tmp_path, *setup(mode="no_report"))
    assert result.fell_back and result.valid
    assert result.report["confidence"]["level"] == "INSUFFICIENT"
    assert "without writing report.json" in result.fallback_reason


def test_report_invalid_after_three_attempts_falls_back_and_is_kept_for_review(tmp_path, setup):
    result = run(tmp_path, *setup(mode="invalid"))
    assert result.fell_back and result.valid and result.report_attempts == 3
    assert result.report["confidence"]["level"] == "INSUFFICIENT"
    workdir = Path(next(e for e in events(result) if e["type"] == "start")["workdir"])
    assert (workdir / "report.rejected.json").is_file()


def test_claude_failure_falls_back(tmp_path, setup):
    result = run(tmp_path, *setup(mode="crash"))
    assert result.fell_back and result.valid
    assert "exited with code 1" in result.fallback_reason
    assert any(e["type"] == "claude_stderr" for e in events(result))


def test_missing_claude_executable_falls_back(tmp_path, setup):
    incident, _ = setup()
    result = run(tmp_path, incident, str(tmp_path / "no-such-claude"))
    assert result.fell_back and "couldn't start Claude Code" in result.fallback_reason


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_model_never_sees_the_scenario_name(tmp_path, setup, scenario):
    """R20: the first message (workdir + incident) names no scenario."""
    run(tmp_path, *setup(scenario), label=scenario)
    assert scenario not in record(tmp_path)["prompt"]


def test_cli_claude_code_provider(tmp_path, setup, capsys):
    from investigator import cli as investigator_cli
    incident, claude = setup()
    code = investigator_cli.main(["agent", "--provider", "claude-code", "--claude-bin", claude,
                                  "--workdir", str(tmp_path / "case-cli"), "--incident-file", str(incident),
                                  "--rules", str(SKILL), "--runs-dir", str(tmp_path / "runs"), "--label", "cli"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["valid"] is True and out["confidence"] == "HIGH" and out["fell_back"] is False
