"""M9: the report contract. A valid report passes; each rule rejects exactly its violation."""

from __future__ import annotations

import copy
import json

import pytest

from investigator import cli as investigator_cli
from investigator.models import Confidence
from investigator.pipeline import analyse_workdir, score_in_workdir, validate_report_in_workdir
from investigator.report.model import fallback_report
from investigator.report.render_md import render

from test_guardrails import collected
from test_planner import RULES, SKILL


def good_report(work, bundle):
    """What a well-behaved AI would submit for scenario 1, built only from the bundle."""
    by_id = {e.event_id: e for e in bundle.events}
    (h,) = bundle.hypotheses
    scored = score_in_workdir(work, RULES, h.cause_event_id)
    evidence = [h.cause_event_id] + [e for e in h.effect_event_ids[:4]]
    timeline = sorted({h.cause_event_id, bundle.seed.event_id}, key=lambda e: by_id[e].ts_utc)
    return {
        "summary": "A degraded Kafka partition made the upstream publish fail, so the seed timed out.",
        "correlation_id": bundle.seed.correlation_id,
        "timeline": [{"event_id": e, "note": "step"} for e in timeline],
        "root_cause": {"statement": "ISR shrink on the upstream topic partition", "cause_event_id": h.cause_event_id,
                       "evidence_event_ids": evidence, "source": "detector"},
        "evidence": [{"event_id": e, "why": "part of the chain"} for e in evidence],
        "downstream_symptoms": [{"statement": "the seed timed out", "event_ids": [bundle.seed.event_id]}],
        "alternative_hypotheses": [],
        "confidence": {"level": scored.ceiling.value,
                       "factors": [{"name": f.name.value, "value": f.value.value, "reason": "as computed"}
                                   for f in scored.factors]},
        "gaps": [{"target": g.target, "reason": g.reason.value, "impact": "n/a"} for g in bundle.coverage_gaps],
        "ai_interpretations": [],
        "next_steps": ["Check the broker's replica health for the partition."],
    }


@pytest.fixture
def scenario1(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys)
    bundle = analyse_workdir(work, RULES)
    return work, bundle, good_report(work, bundle)


def codes(work, report):
    return {e.code for e in validate_report_in_workdir(work, RULES, report).errors}


def test_a_well_formed_report_is_valid(scenario1):
    work, _, report = scenario1
    assert codes(work, report) == set()


def mutate(report, fn):
    r = copy.deepcopy(report)
    fn(r)
    return r


@pytest.mark.parametrize("change,code", [
    (lambda r: r.pop("next_steps"), "missing_section"),
    (lambda r: r.__setitem__("timeline", "not a list"), "missing_section"),
    (lambda r: r["evidence"].append({"event_id": "ev-invented", "why": "made up"}), "unknown_event_id"),
    (lambda r: r["root_cause"].__setitem__("evidence_event_ids", []), "root_cause_no_evidence"),
    (lambda r: r.__setitem__("evidence", []), "root_cause_no_evidence"),
    (lambda r: r["confidence"]["factors"][0].__setitem__("value", "WEAK"), "factors_mismatch"),
    (lambda r: (r.__setitem__("root_cause", "unknown"), r["confidence"].__setitem__("level", "MEDIUM")),
     "unknown_root_cause_confident"),
    (lambda r: r["confidence"].__setitem__("level", "INSUFFICIENT"), "insufficient_with_cause"),
    (lambda r: r.__setitem__("correlation_id", "c-someone-else"), "wrong_correlation_id"),
    (lambda r: r.__setitem__("gaps", []), "gap_not_acknowledged"),
    (lambda r: r["timeline"].reverse(), "timeline_out_of_order"),
    (lambda r: r["root_cause"].__setitem__("source", "guess"), "bad_value"),
    (lambda r: r["confidence"].__setitem__("level", "CERTAIN"), "bad_value"),
    (lambda r: r.__setitem__("alternative_hypotheses", [{"statement": "x", "event_ids": [], "status": "maybe",
                                                         "why": ""}]), "bad_value"),
])
def test_each_rule_rejects_its_violation(scenario1, change, code):
    work, _, report = scenario1
    assert code in codes(work, mutate(report, change))


def test_an_ai_proposed_cause_cannot_claim_more_than_its_score(scenario1):
    work, bundle, report = scenario1
    unrelated = next(e for e in bundle.events if e.ts_utc and e.ts_utc < bundle.seed.ts_utc
                     and e.event_id != bundle.hypotheses[0].cause_event_id and e.severity.value == "CONTEXT")
    scored = score_in_workdir(work, RULES, unrelated.event_id)
    ai = mutate(report, lambda r: (
        r["root_cause"].update({"cause_event_id": unrelated.event_id, "source": "ai",
                                "evidence_event_ids": [unrelated.event_id]}),
        r.__setitem__("evidence", [{"event_id": unrelated.event_id, "why": "AI thinks so"}]),
        r["confidence"].__setitem__("factors", [{"name": f.name.value, "value": f.value.value, "reason": ""}
                                                for f in scored.factors])))
    assert "confidence_above_ceiling" in codes(work, ai)                     # still claims HIGH
    ai["confidence"]["level"] = scored.ceiling.value
    if scored.ceiling is Confidence.INSUFFICIENT:
        # a named cause can't be INSUFFICIENT: the honest report is root_cause "unknown"
        assert codes(work, ai) == {"insufficient_with_cause"}
    else:
        assert codes(work, ai) == set()  # an honest claim at the ceiling is accepted


def test_fallback_report_is_valid_and_insufficient(scenario1):
    work, bundle, _ = scenario1
    fb = fallback_report(bundle, "the AI's report failed validation 3 times")
    assert codes(work, fb) == set() and fb["confidence"]["level"] == "INSUFFICIENT"
    assert fb["alternative_hypotheses"][0]["status"] == "open"  # the detector lead is kept, unconfirmed


def test_ambiguous_scenario_unknown_and_insufficient_is_valid(tmp_path, monkeypatch, capsys):
    work, _ = collected(tmp_path, monkeypatch, capsys, scenario="ambiguous")
    bundle = analyse_workdir(work, RULES)
    report = fallback_report(bundle, "no evidence chain")
    report["summary"] = "The seed error can't be explained from the collected evidence."
    assert codes(work, report) == set()


def test_render_markdown(scenario1):
    work, _, report = scenario1
    md = render(report, validate_report_in_workdir(work, RULES, report).events)
    for heading in ("# Incident report", "MOCK DATA", "**Confidence:** HIGH", "## Root cause", "## Evidence",
                    "## Timeline", "## Confidence factors", "## Next steps"):
        assert heading in md


def test_cli_validate_and_render(scenario1, tmp_path, monkeypatch, capsys):
    work, _, report = scenario1
    monkeypatch.chdir(SKILL.parents[3])
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(report))
    bad.write_text(json.dumps(mutate(report, lambda r: r["confidence"].__setitem__("level", "CERTAIN"))))
    assert investigator_cli.main(["validate", "--workdir", str(work), "--report", str(good)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert investigator_cli.main(["validate", "--workdir", str(work), "--report", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "bad_value"
    assert investigator_cli.main(["render", "--workdir", str(work), "--report", str(good)]) == 0
    assert capsys.readouterr().out.startswith("# Incident report")
    assert investigator_cli.main(["render", "--workdir", str(work), "--report", str(bad)]) == 1
