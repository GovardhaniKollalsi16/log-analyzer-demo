"""M6 end to end: collect scenario 1 with the planner loop, then classify, correlate and order."""

from __future__ import annotations

import json

from investigator.adapters import FileSource
from investigator.classify import classify
from investigator.correlation import correlate
from investigator.models import LinkKind
from investigator.parsing import parse_all
from investigator.parsing.incident import parse_incident
from investigator.planner import topology_of
from investigator.timeline import build_timeline

from test_planner import RULES, agent_loop, save_incident  # noqa: F401  (fixtures/helpers)
from test_planner import env  # noqa: F401  pytest fixture


def analyse(work):
    inc = parse_incident((work / "incident.txt").read_text(), RULES)
    parsed = parse_all(FileSource(work))
    cor = correlate(classify(parsed.events), inc, topology_of(inc, parsed))
    group = next(g for g in cor.groups if g.group_id == cor.seed_group)
    tl = build_timeline(cor.events, only=group.event_ids)
    return inc, cor, group, tl


def run(env, capsys, monkeypatch, knobs=None):
    if knobs:
        monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs))
    save_incident(env)
    agent_loop(env, capsys)
    return analyse(env)


def first(cor, tl, pred):
    by_id = {e.event_id: e for e in cor.events}
    return next(t for t in tl.entries if pred(by_id[t.event_id]))


def test_seed_group_tells_the_whole_story(env, capsys, monkeypatch):
    inc, cor, group, tl = run(env, capsys, monkeypatch)
    by_id = {e.event_id: e for e in cor.events}
    members = [by_id[e] for e in group.event_ids]
    assert inc.seed.event_id in group.event_ids
    codes = {e.error_code for e in members}
    assert {"app.event_wait_timeout", "app.publish_failed", "kafka.broker.isr_shrink",
            "kafka.producer.retry"} <= codes
    assert {e.app for e in members if e.app} >= {"order-service", "product-service"}
    # the producer client lines exist twice (app logs + kafka logs) and are counted once
    assert cor.copies and all(by_id[c].component == "producer" for c in cor.copies)
    assert {LinkKind.EXACT_ID, LinkKind.BUSINESS_KEY, LinkKind.RESOURCE, LinkKind.SAME_OCCURRENCE} <= \
        {l.kind for l in cor.links}


def test_seed_group_timeline_is_in_true_chronological_order(env, capsys, monkeypatch):
    inc, cor, _, tl = run(env, capsys, monkeypatch)
    isr = first(cor, tl, lambda e: e.error_code == "kafka.broker.isr_shrink")
    first_retry = first(cor, tl, lambda e: e.error_code == "kafka.producer.retry")
    publish_failed = [t for t in tl.entries if next(e for e in cor.events if e.event_id == t.event_id).error_code
                      == "app.publish_failed"][-1]
    seed = next(t for t in tl.entries if t.event_id == inc.seed.event_id)
    assert isr.ts_utc < first_retry.ts_utc < publish_failed.ts_utc < seed.ts_utc


def test_shuffled_input_gives_the_same_groups_and_timeline(env, capsys, monkeypatch, tmp_path):
    _, cor_a, group_a, tl_a = run(env, capsys, monkeypatch)
    other = tmp_path / "shuffled"
    other.mkdir()
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"shuffle": True}))
    save_incident(other)
    agent_loop(other, capsys)
    _, cor_b, group_b, tl_b = analyse(other)
    assert sorted(group_a.event_ids) == sorted(group_b.event_ids)
    assert [t.event_id for t in tl_a.entries] == [t.event_id for t in tl_b.entries]
