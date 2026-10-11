"""M12: the subagent's PreToolUse hook lets Bash run only plain `investigator` commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "allowlist_guard.py"


def hook(payload):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)


def bash(command):
    return hook({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/x"})


@pytest.mark.parametrize("command", [
    "investigator plan --workdir /w/case-1",
    "investigator correlate --workdir /w/case-1",
    "investigator run --workdir /w/case-1 --reason 'seed app errors' -- mocklogs kubectl logs deploy/a",
    "investigator score --workdir /w/case-1 --cause ev-123",
    "investigator validate --workdir /w/case-1 --report /w/case-1/report.json",
])
def test_plain_investigator_commands_are_allowed(command):
    r = bash(command)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("command, why", [
    ("cat /etc/passwd", "only `investigator ...` commands"),
    ("mocklogs sso login", "only `investigator ...` commands"),
    ("investigator agent --workdir /w", "isn't allowed"),
    ("investigator plan --workdir /w && rm -rf /w", "'&&'"),
    ("investigator plan --workdir /w; ls", "';'"),
    ("investigator plan --workdir /w | tee x", "'|'"),
    ("investigator plan --workdir /w > out", "'>'"),
    ("investigator plan --workdir $(whoami)", "'$('"),
    ("investigator plan --workdir `id`", "'`'"),
    ("investigator plan --workdir ${HOME}", "'${'"),
    ("investigator plan --workdir 'unclosed", "parse"),
    ("", "only `investigator ...` commands"),
])
def test_everything_else_is_blocked_with_a_reason_for_the_model(command, why):
    r = bash(command)
    assert r.returncode == 2
    assert r.stderr.startswith("Blocked by the incident-investigator guard")
    assert why in r.stderr


def test_other_tools_pass_through():
    assert hook({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}).returncode == 0
