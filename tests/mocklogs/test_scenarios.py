"""Every scenario generator: deterministic, well-formed incident, evidence marked critical, no cross-scenario leaks."""

from __future__ import annotations

import pytest

from investigator.correlation_keys import load_rules
from investigator.parsing.incident import parse_incident
from mocklogs.render import incident_text
from mocklogs.scenarios import SCENARIOS, load
from mocklogs.scenarios.base import ScenarioKnobs

from pathlib import Path

RULES = load_rules(Path(__file__).resolve().parents[2] / ".claude" / "skills" / "incident-logs" / "SKILL.md")


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_is_deterministic_and_seeded(name):
    a, b, c = load(name), load(name), load(name, ScenarioKnobs(seed=99))
    ids = lambda w: [l.correlation_id for l in w.app_logs if l.correlation_id]  # noqa: E731
    assert ids(a) == ids(b) and ids(a) != ids(c)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_incident_parses_and_seed_is_a_critical_error(name):
    w = load(name)
    inc = parse_incident(incident_text(w), RULES)
    assert w.incident.seed_record.level == "ERROR" and w.incident.seed_record.critical
    assert inc.seed.app == w.incident.seed_record.app


@pytest.mark.parametrize("name,business_key", [("upstream-timeout", "order_id"), ("db-config", "order_id"),
                                               ("consumer-processing", "order_id"), ("ambiguous", None)])
def test_business_key_per_scenario(name, business_key):
    assert parse_incident(incident_text(load(name)), RULES).seed.business_key == business_key


def test_ambiguous_always_denies_the_seed_config_even_with_other_denials():
    w = load("ambiguous", ScenarioKnobs(access_denied=frozenset({"logs:other_app"})))
    assert {"config:edge-gateway", "logs:order-service"} <= w.denied
