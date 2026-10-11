"""M10: `investigator run` (checked, shell-free execution + action log) and `investigator init` (R17)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from investigator import cli as investigator_cli
from investigator.adapters import FileSource
from mocklogs import cli as mock_cli, sso

from test_planner import SKILL

ROOT = SKILL.parents[3]
BIN = Path(__import__("sys").executable).parent  # the venv's bin (holds `mocklogs`)
W = ["--since-time=2026-03-14T08:50:00Z", "--until-time=2026-03-14T09:10:00Z"]


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", "upstream-timeout")
    monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    monkeypatch.setenv("PATH", f"{BIN}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(ROOT)
    sso.login()
    incident = tmp_path / "incident-from-user.txt"
    incident.write_text("\n".join(mock_cli.run(["scenario", "incident"]).out))
    w = tmp_path / "work"
    assert investigator_cli.main(["init", "--workdir", str(w), "--incident-file", str(incident)]) == 0
    return w


def run(work, reason, *argv):
    return investigator_cli.main(["run", "--workdir", str(work), "--reason", reason, "--", *argv])


def actions(work):
    return [json.loads(l) for l in (work / "actions.jsonl").read_text().splitlines()]


def test_init_saves_the_incident_verbatim_and_refuses_a_different_one(work, tmp_path, capsys):
    saved = (work / "incident.txt").read_text()
    assert saved.startswith("INCIDENT\nseed: ")  # exactly the file the user gave, not retyped
    other = tmp_path / "other.txt"
    other.write_text(saved.replace("o-1008", "o-9999"))
    assert investigator_cli.main(["init", "--workdir", str(work), "--incident-file", str(other)]) == 2
    bad = tmp_path / "bad.txt"
    bad.write_text("INCIDENT\napp: cluster=c namespace=n")
    assert investigator_cli.main(["init", "--workdir", str(tmp_path / "w2"), "--incident-file", str(bad)]) == 2
    assert "no seed line" in capsys.readouterr().err


def test_allowed_command_runs_and_is_saved_and_logged(work, capsys):
    code = run(work, "seed app lines for the order", "mocklogs", "kubectl", "logs", "deploy/order-service",
               "--context", "cluster-a", "-n", "apps", *W, "--grep", "o-1008", "--save-dir", str(work))
    out = capsys.readouterr().out
    assert code == 0 and "Timed out waiting for pricing event" in out
    assert len(list(FileSource(work).outputs())) == 1
    (a,) = actions(work)
    assert a["allowed"] is True and a["exit_code"] == 0 and a["reason"] == "seed app lines for the order"


def test_denied_command_never_runs_but_is_logged(work, capsys):
    code = run(work, "curious", "mocklogs", "kubectl", "logs", "deploy/edge-gateway", "--context", "cluster-a",
               "-n", "apps", *W, "--save-dir", str(work))
    assert code == 1 and json.loads(capsys.readouterr().out)["reasons"][0]["code"] == "app_not_related"
    assert list(FileSource(work).outputs()) == []  # nothing was fetched
    (a,) = actions(work)
    assert a["allowed"] is False and a["denials"][0]["code"] == "app_not_related" and a["reason"] == "curious"


@pytest.mark.parametrize("argv,code", [
    (["mocklogs", "kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps", "--grep",
      "x | cat /etc/passwd"], "shell_metachar"),
    (["mocklogs", "kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps", "--grep",
      "$(whoami)"], "shell_metachar"),
    (["mocklogs", "sso", "login"], "not_allowed_for_agent"),
    (["mocklogs", "kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps", "--follow"],
     "flag_not_allowed"),
    (["bash", "-c", "mocklogs kubectl logs deploy/order-service"], "unknown_tool"),
])
def test_runner_refuses_dangerous_or_undocumented_commands(work, capsys, argv, code):
    assert run(work, "test", *argv, "--save-dir", str(work)) == 1
    assert code in {r["code"] for r in json.loads(capsys.readouterr().out)["reasons"]}


def test_refusal_exit_codes_pass_through(work, capsys, monkeypatch):
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"access_denied": ["config:seed_app"]}))
    code = run(work, "seed config", "mocklogs", "kubectl", "get", "configmap", "order-service-config",
               "--context", "cluster-a", "-n", "apps", "-o", "json", "--save-dir", str(work))
    assert code == 4 and actions(work)[-1]["exit_code"] == 4  # Forbidden from the tool, not a guard denial
