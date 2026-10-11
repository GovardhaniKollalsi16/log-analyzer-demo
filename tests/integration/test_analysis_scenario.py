"""M7 end to end: planner loop -> investigator correlate (bundle) on scenario 1 and degraded variants."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from investigator import cli as investigator_cli
from investigator.models import Confidence, to_jsonable
from investigator.pipeline import analyse_workdir

from test_planner import RULES, SKILL, agent_loop, env, save_incident  # noqa: F401  (env is a fixture)

SNAPSHOT = Path(__file__).parent / "snapshots" / "scenario1_bundle_summary.json"


def bundle_for(env, capsys, monkeypatch, knobs=None):
    if knobs:
        monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs))
    save_incident(env)
    agent_loop(env, capsys)
    return analyse_workdir(env, RULES)


def summary(bundle):
    by_id = {e.event_id: e for e in bundle.events}
    return {
        "confidence_cap": bundle.confidence_cap.value,
        "findings": sorted(f"{f.detector}: {f.summary}" for f in bundle.findings),
        "hypotheses": [{
            "cause": f"{by_id[h.cause_event_id].error_code} | {by_id[h.cause_event_id].message[:60]}",
            "factors": {f.name.value: f.value.value for f in h.factors},
            "ceiling": h.ceiling.value,
        } for h in bundle.hypotheses],
        "gaps": sorted(f"{g.component.value}:{g.target}:{g.reason.value}" for g in bundle.coverage_gaps),
    }


def test_scenario1_is_high_with_the_isr_shrink_as_the_only_cause(env, capsys, monkeypatch):
    b = bundle_for(env, capsys, monkeypatch)
    assert b.confidence_cap is Confidence.HIGH
    (h,) = b.hypotheses
    cause = next(e for e in b.events if e.event_id == h.cause_event_id)
    assert cause.error_code == "kafka.broker.isr_shrink"
    assert b.seed.event_id in h.effect_event_ids
    assert {f.detector for f in b.findings} >= {"retry_exhaustion", "delivery_failure_chain", "missing_message"}


@pytest.mark.parametrize("knobs", [{"access_denied": ["config:seed_app"]}, {"omit_inputs": ["related"]}])
def test_degraded_collection_lowers_the_ceiling(env, capsys, monkeypatch, knobs):
    b = bundle_for(env, capsys, monkeypatch, knobs)
    assert b.confidence_cap is Confidence.LOW
    assert len(b.hypotheses) == 1  # one repeated pattern, not rivals


def test_missing_kafka_input_means_insufficient_or_low_never_high(env, capsys, monkeypatch):
    b = bundle_for(env, capsys, monkeypatch, {"omit_inputs": ["kafka"]})
    assert b.confidence_cap in (Confidence.INSUFFICIENT, Confidence.LOW)


def test_every_citation_in_the_bundle_points_at_a_bundle_event(env, capsys, monkeypatch):
    b = bundle_for(env, capsys, monkeypatch)
    ids = b.event_ids()
    assert all(e in ids for f in b.findings for e in f.event_ids)
    for h in b.hypotheses:
        assert h.cause_event_id in ids and set(h.effect_event_ids) <= ids
    assert {t.event_id for t in b.timeline} <= ids
    assert b.seed.event_id in ids


def test_bundle_summary_snapshot(env, capsys, monkeypatch):
    actual = summary(bundle_for(env, capsys, monkeypatch))
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(actual, indent=2) + "\n")
    assert actual == json.loads(SNAPSHOT.read_text())


def test_cli_correlate_prints_the_bundle(env, capsys, monkeypatch):
    save_incident(env)
    agent_loop(env, capsys)
    monkeypatch.chdir(SKILL.parents[3])
    assert investigator_cli.main(["correlate", "--workdir", str(env)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["confidence_cap"] == "HIGH" and out["hypotheses"][0]["ceiling"] == "HIGH"
    assert json.loads(json.dumps(to_jsonable(analyse_workdir(env, RULES)))) == out
