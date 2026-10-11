"""M8b: `investigator check` (every command the AI runs) and `investigator score` (any cause the AI proposes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from investigator import cli as investigator_cli
from investigator.adapters import FileSource
from investigator.guard import check
from investigator.models import Confidence
from investigator.parsing import parse_all
from investigator.pipeline import analyse_workdir, prepare, score_in_workdir
from investigator.planner import plan
from mocklogs import cli as mock_cli, sso
from mocklogs.scenarios import SCENARIOS

from test_planner import RULES, SKILL

W = ["--since-time=2026-03-14T08:50:00Z", "--until-time=2026-03-14T09:10:00Z"]


def collected(tmp_path, monkeypatch, capsys, scenario="upstream-timeout", knobs=None):
    """Run the planner loop to completion, checking EVERY planned command with the guard first."""
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", scenario)
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs or {}))
    sso.login()
    work = tmp_path / "work"
    work.mkdir()
    (work / "incident.txt").write_text("\n".join(mock_cli.run(["scenario", "incident"]).out))
    denied = []
    for _ in range(10):
        p = prepare(work, RULES)
        source = FileSource(work)
        steps = plan(p.incident, parse_all(source), list(source.outputs()), str(work))
        if steps.done:
            break
        for step in steps.steps:
            verdict = check(step.argv, p.incident, p.topology, str(work))
            if not verdict.allowed:
                denied.append((step.argv, verdict.reasons))
            mock_cli.main(step.argv[1:])
    capsys.readouterr()
    return work, denied


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_planner_step_passes_the_guard(tmp_path, monkeypatch, capsys, scenario):
    _, denied = collected(tmp_path, monkeypatch, capsys, scenario)
    assert denied == []


def verdict(work, *args):
    p = prepare(work, RULES)
    return check(["mocklogs", *args, "--save-dir", str(work)], p.incident, p.topology, str(work))


def test_ai_may_go_beyond_the_planner_within_the_rules(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    # a wider window and a different search on a declared upstream app: not a planner step, but legal
    v = verdict(work, "kubectl", "logs", "deploy/product-service", "--context", "cluster-a", "-n", "apps",
                "--timestamps", "--since-time=2026-03-14T08:00:00Z", "--until-time=2026-03-14T10:00:00Z",
                "--grep", "Expiring")
    assert v.allowed, v.reasons


@pytest.mark.parametrize("args,code", [
    (["kubectl", "logs", "deploy/edge-gateway", "--context", "cluster-a", "-n", "apps", *W], "app_not_related"),
    (["kubectl", "logs", "deploy/order-service", "--context", "cluster-b", "-n", "apps", *W], "location_mismatch"),
    (["kubectl", "get", "configmap", "product-service-config", "--context", "cluster-a", "-n", "apps", "-o", "json"],
     "config_not_seed"),
    (["kafka", "logs", "--bootstrap-server", "kafka-a:9092", "--component", "broker", "--topic", "other.topic", *W],
     "topic_not_in_incident"),
    (["kafka-get-offsets", "--bootstrap-server", "kafka-b:9092", "--topic", "pricing.events", "--time", "0"],
     "location_mismatch"),
    (["db", "logs", "--host", "db-a", "--db", "appdb", *W], "input_missing"),  # scenario 1 incident has no db: line
    (["kafka-consumer-groups", "--bootstrap-server", "kafka-a:9092", "--describe", "--group", "g"],
     "not_in_collection_scope"),
    (["sso", "login"], "not_allowed_for_agent"),
    (["kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps", "--follow"], "flag_not_allowed"),
    (["kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps", "--grep", "x; rm -rf /"],
     "shell_metachar"),
    (["kubectl", "exec", "deploy/order-service"], "unknown_command"),
])
def test_guard_denials(tmp_path, monkeypatch, capsys, args, code):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    v = verdict(work, *args)
    assert not v.allowed and code in {r["code"] for r in v.reasons}, v.reasons


def test_output_must_be_saved_to_the_workdir(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    p = prepare(work, RULES)
    argv = ["mocklogs", "kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps", *W]
    for extra in ([], ["--save-dir", str(tmp_path / "elsewhere")]):
        v = check(argv + extra, p.incident, p.topology, str(work))
        assert not v.allowed and "save_dir_missing" in {r["code"] for r in v.reasons}


def test_related_app_needs_its_incident_line(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys, knobs={"omit_inputs": ["related"]})
    v = verdict(work, "kubectl", "logs", "deploy/product-service", "--context", "cluster-a", "-n", "apps", *W)
    assert not v.allowed and "input_missing" in {r["code"] for r in v.reasons}


def test_without_seed_config_no_related_app_is_allowed(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys, knobs={"access_denied": ["config:seed_app"]})
    v = verdict(work, "kubectl", "logs", "deploy/product-service", "--context", "cluster-a", "-n", "apps", *W)
    assert not v.allowed and "app_not_related" in {r["code"] for r in v.reasons}


# --- score ----------------------------------------------------------------------------------

def test_scoring_the_detector_cause_matches_the_bundle(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    bundle = analyse_workdir(work, RULES)
    (h,) = bundle.hypotheses
    scored = score_in_workdir(work, RULES, h.cause_event_id)
    assert scored.ceiling is h.ceiling is Confidence.HIGH


def test_an_ai_cause_that_comes_after_the_seed_is_insufficient(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    p = prepare(work, RULES)
    later = next(e for e in p.cor.events if e.ts_utc and e.ts_utc > p.incident.seed.ts_utc and e.app == "order-service")
    assert score_in_workdir(work, RULES, later.event_id).ceiling is Confidence.INSUFFICIENT


def test_an_unlinked_ai_cause_scores_low_and_names_the_rival(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    p = prepare(work, RULES)
    # a collected but unrelated event: a consumer subscribing at startup (no ID, no key, no partition)
    unrelated = next(e for e in p.cor.events if "Subscribed to topic" in e.message
                     and e.ts_utc < p.incident.seed.ts_utc)
    scored = score_in_workdir(work, RULES, unrelated.event_id)
    factors = {f.name.value: f.value.value for f in scored.factors}
    assert scored.ceiling in (Confidence.LOW, Confidence.INSUFFICIENT)
    assert factors["competing_hypotheses"] == "WEAK"  # the detector's ISR-shrink hypothesis is linked more strongly


def test_score_rejects_unknown_events(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    with pytest.raises(KeyError):
        score_in_workdir(work, RULES, "ev-doesnotexist")


# --- CLI --------------------------------------------------------------------------------------

def test_cli_check_and_score(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    monkeypatch.chdir(SKILL.parents[3])
    ok = investigator_cli.main(["check", "--workdir", str(work), "--", "mocklogs", "kubectl", "logs",
                                "deploy/order-service", "--context", "cluster-a", "-n", "apps", *W,
                                "--save-dir", str(work)])
    assert ok == 0 and json.loads(capsys.readouterr().out)["allowed"] is True
    bad = investigator_cli.main(["check", "--workdir", str(work), "--", "mocklogs", "sso", "login"])
    assert bad == 1 and json.loads(capsys.readouterr().out)["reasons"][0]["code"] == "not_allowed_for_agent"
    cause = analyse_workdir(work, RULES).hypotheses[0].cause_event_id
    assert investigator_cli.main(["score", "--workdir", str(work), "--cause", cause]) == 0
    assert json.loads(capsys.readouterr().out)["ceiling"] == "HIGH"
    assert investigator_cli.main(["score", "--workdir", str(work), "--cause", "ev-nope"]) == 2
