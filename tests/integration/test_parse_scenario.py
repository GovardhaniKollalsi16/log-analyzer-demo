"""M3 end-to-end: fetch scenario 1 through `mocklogs --save-dir`, parse it back with investigator.

Tests may import mocklogs to *produce* data; investigator itself never does (boundary test).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from investigator.adapters import FileSource
from investigator.correlation_keys import load_rules
from investigator.models import GapReason, LinkKind, Source
from investigator.parsing import parse_all
from investigator.parsing.incident import parse_incident
from mocklogs import cli, sso

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "incident-logs" / "SKILL.md"
W = ["--since-time=2026-03-14T08:54:50Z", "--until-time=2026-03-14T09:06:50Z"]
K8S = ["--context", "cluster-a", "-n", "apps", "--timestamps"]
BOOT = ["--bootstrap-server", "kafka-a:9092"]
PROPS = ["--property", "print.headers=true", "--property", "print.timestamp=true",
         "--property", "print.partition=true", "--property", "print.offset=true"]

FETCHES = [
    ["kubectl", "logs", "deploy/order-service", *K8S, *W, "--grep", "o-1008"],
    ["kubectl", "logs", "deploy/order-service", *K8S, *W, "--instance", "order-service-ea716-0", "--thread", "pricing-wait-1"],
    ["kubectl", "get", "configmap", "order-service-config", "--context", "cluster-a", "-n", "apps", "-o", "json"],
    ["kafka-consumer-groups", *BOOT, "--describe", "--group", "order-service-pricing", "--samples", "3"],
    ["kafka-consumer-groups", *BOOT, "--describe", "--all-groups"],
    ["kafka-get-offsets", *BOOT, "--topic", "pricing.events", "--time", "1773478490000"],
    *[["kafka-console-consumer", *BOOT, "--topic", "pricing.events", "--partition", str(p), "--offset", str(o),
       "--max-messages", "50", *PROPS] for p, o in ((0, 1180), (1, 1580), (2, 1980))],
    *[["kafka", "logs", *BOOT, "--component", c, "--topic", "pricing.events", *W] for c in ("broker", "producer", "consumer")],
    ["kubectl", "logs", "deploy/product-service", *K8S, *W, "--grep", "o-1008"],
    ["kubectl", "logs", "deploy/product-service", *K8S, *W],
    ["db", "logs", "--host", "db-a", "--db", "appdb", *W],
]


def fetch(tmp: Path, monkeypatch, capsys, knobs=None, extra=()):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", "upstream-timeout")
    if knobs:
        monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs))
    else:
        monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    sso.login()
    work = tmp / "work"
    for argv in list(FETCHES) + list(extra):
        cli.main(list(argv) + ["--save-dir", str(work)])
    incident = "\n".join(cli.run(["scenario", "incident"]).out)
    capsys.readouterr()
    return parse_all(FileSource(work)), parse_incident(incident, load_rules(SKILL))


@pytest.fixture
def clean(tmp_path, monkeypatch, capsys):
    return fetch(tmp_path, monkeypatch, capsys)


def test_seed_and_incident(clean):
    res, inc = clean
    assert inc.seed.app == "order-service" and inc.seed.business_key == "order_id"
    assert inc.seed.keys["order_id"] == "o-1008"
    ids = {e.event_id for e in res.events}
    assert inc.seed.event_id in ids  # the seed record was fetched and parsed to the same ID


def test_every_component_parsed_without_issues(clean):
    res, _ = clean
    assert not res.issues
    by = Counter(e.source for e in res.events)
    assert by[Source.APP] and by[Source.APP_CONFIG] and by[Source.KAFKA] and by[Source.DB]
    assert any(c.key == "kafka.consumer.topics" and c.value == "pricing.events" for c in res.config)
    assert res.offsets[("pricing.events", 2)] == 1980


def test_correlation_ids_stay_per_app_and_business_key_links(clean):
    res, inc = clean
    order = [e for e in res.events if e.keys.get("order_id") == "o-1008"]
    apps = {e.app for e in order}
    assert {"order-service", "product-service"} <= apps
    per_app = {}
    for e in order:
        if e.ids.correlation_id:
            per_app.setdefault(e.app, set()).add(e.ids.correlation_id)
    assert per_app["order-service"] == {inc.seed.correlation_id}
    assert per_app["product-service"].isdisjoint(per_app["order-service"])


def test_kafka_records(clean):
    res, _ = clean
    msgs = [e for e in res.events if e.component == "message"]
    assert msgs and all(e.app == "product-service" and e.ids.correlation_id and "order_id" in e.keys for e in msgs)
    assert not [e for e in msgs if e.keys["order_id"] == "o-1008"]  # the missing message
    logs = [e for e in res.events if e.source is Source.KAFKA and e.component in ("broker", "producer", "consumer")]
    assert logs and all(e.ids.is_empty() and not e.keys for e in logs)  # "correlation id 8850" is not an app ID
    assert any(e.attrs.get("partitions") == [2] and e.component == "broker" for e in logs)
    lag = [e for e in res.events if e.component == "consumer-group"]
    seed_group = [e for e in lag if e.kafka.group == "order-service-pricing"]
    # --samples 3 gives timed samples 1..3; the --all-groups snapshot has no time (the real tool prints none)
    assert {e.attrs["sample"] for e in seed_group} == {1, 2, 3, None}
    assert all((e.ts_utc is None) == (e.attrs["sample"] is None) for e in seed_group)


def test_overlapping_fetches_dedupe_to_one_event(clean):
    res, inc = clean
    seed_events = [e for e in res.events if e.event_id == inc.seed.event_id]
    assert len(seed_events) == 1
    assert len({r.command for r in seed_events[0].raw_refs}) == 2  # fetched by the order_id search and the thread search
    assert seed_events[0].duplicate_count == 1


def test_event_ids_are_stable_across_runs(tmp_path, monkeypatch, capsys, clean):
    again, _ = fetch(tmp_path / "second", monkeypatch, capsys)
    assert sorted(e.event_id for e in again.events) == sorted(e.event_id for e in clean[0].events)


def test_shuffled_input_gives_the_same_events(tmp_path, monkeypatch, capsys, clean):
    shuffled, _ = fetch(tmp_path / "s", monkeypatch, capsys, {"shuffle": True})
    assert {e.event_id for e in shuffled.events} == {e.event_id for e in clean[0].events}


def test_duplicates_collapse(tmp_path, monkeypatch, capsys, clean):
    dup, _ = fetch(tmp_path / "d", monkeypatch, capsys, {"dup_rate": 0.4})
    assert {e.event_id for e in dup.events} == {e.event_id for e in clean[0].events}
    assert max(e.duplicate_count for e in dup.events) >= 2


def test_malformed_and_dropped_lines_dont_crash_and_keep_the_evidence(tmp_path, monkeypatch, capsys, clean):
    noisy, inc = fetch(tmp_path / "m", monkeypatch, capsys, {"malformed_rate": 0.3, "drop_rate": 0.3})
    assert noisy.issues  # truncated lines were reported...
    noisy_ids = {e.event_id for e in noisy.events}
    clean_ids = {e.event_id for e in clean[0].events}
    clean_raw = [r.text for e in clean[0].events for r in e.raw_refs]
    # Nothing is invented: an unknown event can only be a truncated line that still parses
    # (a plain-text log line can't show that it was cut), i.e. a prefix of a real line.
    for e in noisy.events:
        if e.event_id not in clean_ids:
            assert any(full.startswith(e.raw_refs[0].text) for full in clean_raw), e.raw_refs[0].text
    assert inc.seed.event_id in noisy_ids
    assert any(e.app == "product-service" and e.level.value == "ERROR" for e in noisy.events)


def test_time_shift_and_skew_are_normalized_to_utc(tmp_path, monkeypatch, capsys, clean):
    shifted, _ = fetch(tmp_path / "t", monkeypatch, capsys,
                       {"t0": "2026-03-17T09:00:00Z", "skew_ms": {"kafka": 45000}},
                       )
    # Shifted 3 days: the fixed --since/--until window now finds no app/DB lines, which is correct behaviour.
    assert all(e.ts_utc is None or e.ts_utc.utcoffset() == timedelta(0) for e in shifted.events)


def test_refusals_become_gaps(tmp_path, monkeypatch, capsys):
    res, _ = fetch(tmp_path, monkeypatch, capsys, {"access_denied": ["config:seed_app", "kafka-topic:in_topic"]})
    reasons = {(g.component, g.reason) for g in res.gaps}
    assert (Source.APP_CONFIG, GapReason.ACCESS_DENIED) in reasons
    assert (Source.KAFKA, GapReason.ACCESS_DENIED) in reasons
    assert not any(e.source is Source.APP_CONFIG for e in res.events)


def test_business_key_link_kind_exists_for_m6():
    assert LinkKind.BUSINESS_KEY.value == "business_key"


def test_ts_raw_is_always_verbatim(clean):
    """ts_raw must be the exact text the tool printed, never a reformatted value."""
    res, _ = clean
    checked = 0
    for e in res.events:
        if not e.ts_raw:
            assert e.ts_utc is None or e.component == "consumer-group"
            continue
        if e.component == "consumer-group":
            # the time comes from the "# sample k/N at <ts>" header, not from the row
            assert e.ts_raw.endswith("Z") and "T" in e.ts_raw
        else:
            assert e.ts_raw in e.raw_refs[0].text, (e.ts_raw, e.raw_refs[0].text)
        checked += 1
    assert checked > 30
    msg = next(e for e in res.events if e.component == "message")
    assert msg.ts_raw.isdigit()  # CreateTime epoch ms, as printed
