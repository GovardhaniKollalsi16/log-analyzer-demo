"""M5: `investigator plan` driving collection end to end, as the agent would."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from investigator import cli as investigator_cli
from investigator.adapters import FileSource
from investigator.config_model import attribute_clients, build_topology
from investigator.correlation_keys import load_rules
from investigator.models import Direction, GapReason, Source
from investigator.parsing import parse_all
from investigator.parsing.incident import parse_incident
from investigator.planner import plan
from mocklogs import cli as mock_cli, sso

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "incident-logs" / "SKILL.md"
RULES = load_rules(SKILL)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", "upstream-timeout")
    monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    sso.login()
    work = tmp_path / "work"
    work.mkdir()
    return work


def set_knobs(monkeypatch, knobs):
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs))


def save_incident(work: Path, edit=lambda t: t) -> str:
    text = edit("\n".join(mock_cli.run(["scenario", "incident"]).out))
    (work / "incident.txt").write_text(text)
    return text


def plan_once(work: Path):
    incident = parse_incident((work / "incident.txt").read_text(), RULES)
    source = FileSource(work)
    return plan(incident, parse_all(source), list(source.outputs()), str(work))


def agent_loop(work: Path, capsys, max_rounds=8, before_run=lambda step: None):
    rounds = []
    for _ in range(max_rounds):
        p = plan_once(work)
        rounds.append(p)
        if p.done:
            break
        for step in p.steps:
            assert step.argv[0] == "mocklogs" and "--save-dir" in step.argv
            before_run(step)
            mock_cli.main(step.argv[1:])
    capsys.readouterr()
    return rounds


def fetched(rounds) -> List:
    return [s for r in rounds for s in r.steps]


def apps_fetched(rounds):
    return {s.target for s in fetched(rounds) if s.component is Source.APP}


# --- scenario 1, default incident --------------------------------------------------------

def test_scenario1_converges_and_collects_what_the_skills_describe(env, capsys):
    save_incident(env)
    rounds = agent_loop(env, capsys)
    assert rounds[-1].done and rounds[-1].stop_reason == "no remaining fetches"
    assert len(rounds) == 4
    reasons = [s.reason for s in fetched(rounds)]
    assert reasons[0] == "seed app: its own correlation ID"
    assert any("thread segment" in r and "seed" in r for r in reasons)
    assert any(r.startswith("seed app config") for r in reasons)
    for topic in ("pricing.events", "orders.events"):
        for component in ("producer", "consumer", "broker"):
            assert f"{component} logs for {topic}: retries, errors, timeouts" in reasons
    assert sum("incoming messages on pricing.events-" in r for r in reasons) == 3   # one per partition
    assert sum("outgoing messages on orders.events-" in r for r in reasons) == 3
    # the config's declared apps, one hop, and nothing else (edge-gateway is never declared)
    assert apps_fetched(rounds) == {"order-service", "product-service", "fulfillment-worker", "notification-worker"}
    directions = {s.target: s.direction for s in fetched(rounds) if s.component is Source.APP}
    assert directions["product-service"] is Direction.UPSTREAM and directions["fulfillment-worker"] is Direction.DOWNSTREAM
    # the upstream app's own correlation ID was discovered and followed
    assert any(r.startswith("upstream app product-service: its own correlation ID c-") for r in reasons)
    assert [(g.component, g.reason) for g in rounds[-1].gaps] == [(Source.DB, GapReason.MISSING_INPUT)]


def test_plan_is_idempotent_once_done(env, capsys):
    save_incident(env)
    agent_loop(env, capsys)
    again = plan_once(env)
    assert again.done and again.steps == []


def test_every_planned_command_ran_exactly_once(env, capsys):
    save_incident(env)
    rounds = agent_loop(env, capsys)
    argvs = [tuple(s.argv) for s in fetched(rounds)]
    assert len(argvs) == len(set(argvs))
    assert len(list(FileSource(env).outputs())) == len(argvs)


# --- no input, no access ----------------------------------------------------------------

def test_missing_kafka_line_means_no_kafka_commands(env, capsys, monkeypatch):
    set_knobs(monkeypatch, {"omit_inputs": ["kafka"]})
    save_incident(env)
    rounds = agent_loop(env, capsys)
    assert not any(s.component is Source.KAFKA for s in fetched(rounds))
    assert any(g.component is Source.KAFKA and g.reason is GapReason.MISSING_INPUT for g in rounds[-1].gaps)


def test_missing_related_lines_means_related_apps_skipped(env, capsys, monkeypatch):
    set_knobs(monkeypatch, {"omit_inputs": ["related"]})
    save_incident(env)
    rounds = agent_loop(env, capsys)
    assert apps_fetched(rounds) == {"order-service"}
    skipped = {g.target for g in rounds[-1].gaps if g.reason is GapReason.MISSING_INPUT and g.component is Source.APP}
    assert skipped == {"product-service", "fulfillment-worker", "notification-worker"}


def test_missing_app_line_blocks_seed_logs_config_and_related(env, capsys, monkeypatch):
    set_knobs(monkeypatch, {"omit_inputs": ["app"]})
    save_incident(env)
    rounds = agent_loop(env, capsys)
    assert not any(s.component in (Source.APP, Source.APP_CONFIG) for s in fetched(rounds))
    assert any(s.component is Source.KAFKA for s in fetched(rounds))  # Kafka inputs are still there
    gap_targets = {g.target for g in rounds[-1].gaps}
    assert {"order-service", "order-service-config", "related apps"} <= gap_targets


def test_config_denied_means_related_apps_unknown(env, capsys, monkeypatch):
    set_knobs(monkeypatch, {"access_denied": ["config:seed_app"]})
    save_incident(env)
    rounds = agent_loop(env, capsys)
    assert apps_fetched(rounds) == {"order-service"}
    assert any(g.target == "related apps" and "seed config unavailable" in g.detail for g in rounds[-1].gaps)
    message_reasons = [s.reason for s in fetched(rounds) if "kafka-console-consumer" in s.argv]
    assert message_reasons and all(r.startswith("direction unknown messages on") for r in message_reasons)


def test_no_business_key_means_no_cross_service_searches(env, capsys):
    # The seed's class no longer matches an Order*/Product* rule -> no business key (D25)
    save_incident(env, lambda t: t.replace("orders.OrderPricingAwaiter", "orders.PricingAwaiter"))
    rounds = agent_loop(env, capsys)
    assert not any("kafka-console-consumer" in s.argv for s in fetched(rounds))
    assert apps_fetched(rounds) == {"order-service"}
    details = {g.detail for g in rounds[-1].gaps}
    assert "business key for the message search" in details
    assert "business key for searching a related app" in details


# --- SSO: retry once after the user re-authenticates ---------------------------------------

def test_auth_failure_is_retried_once_then_settles(env, capsys):
    save_incident(env)
    sso.logout()  # the session expired before the agent started
    first = plan_once(env)
    for step in first.steps:
        mock_cli.main(step.argv[1:])
    second = plan_once(env)  # everything failed with exit 3: planned again, once
    assert {tuple(s.argv) for s in second.steps} == {tuple(s.argv) for s in first.steps}
    for step in second.steps:
        mock_cli.main(step.argv[1:])
    third = plan_once(env)  # user never logged in: no more retries
    capsys.readouterr()
    assert third.done
    assert any(g.reason is GapReason.MISSING_INPUT for g in third.gaps)


# --- topology & client attribution (D26) ---------------------------------------------------

def test_topology_from_seed_config_and_declared_client_ids_only(env, capsys):
    save_incident(env)
    agent_loop(env, capsys)
    parsed = parse_all(FileSource(env))
    topo = build_topology("order-service", parsed.config)
    assert topo.upstream_apps == ["product-service"]
    assert topo.downstream_apps == ["fulfillment-worker", "notification-worker"]
    assert [s.topic for s in topo.consumes] == ["pricing.events"] and topo.produces == ["orders.events"]
    assert topo.client_ids == {
        "order-service-consumer-1": "order-service", "order-service-producer-1": "order-service",
        "product-service-producer-1": "product-service",
        "fulfillment-worker-consumer-1": "fulfillment-worker", "notification-worker-consumer-1": "notification-worker",
    }
    attributed = attribute_clients(parsed.events, topo)
    producer = [e for e in attributed if e.component == "producer"]
    assert producer and all(e.app == "product-service" and e.attrs["app_attribution"] == "seed config" for e in producer)


def test_undeclared_client_ids_stay_unattributed(env, capsys):
    save_incident(env)
    agent_loop(env, capsys)
    parsed = parse_all(FileSource(env))
    topo = build_topology("order-service", parsed.config)
    topo.client_ids.pop("product-service-producer-1")  # as if the config didn't declare it
    producer = [e for e in attribute_clients(parsed.events, topo) if e.component == "producer"]
    assert producer and all(e.app is None for e in producer)


# --- CLI ----------------------------------------------------------------------------------

def test_cli_plan_prints_json(env, capsys, monkeypatch):
    save_incident(env)
    monkeypatch.chdir(SKILL.parents[3])
    assert investigator_cli.main(["plan", "--workdir", str(env)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["done"] is False and out["steps"][0]["argv"][:3] == ["mocklogs", "kubectl", "logs"]


def test_cli_plan_without_incident_fails_clearly(tmp_path, capsys):
    assert investigator_cli.main(["plan", "--workdir", str(tmp_path), "--rules", str(SKILL)]) == 2
    assert "incident.txt not found" in capsys.readouterr().err
