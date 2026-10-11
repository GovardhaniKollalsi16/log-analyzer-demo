"""M4 end-to-end: classification on real mocklogs output, and invariance under renaming."""

from __future__ import annotations

from collections import Counter

import pytest

from investigator.adapters import FileSource
from investigator.adapters.base import RawOutput
from investigator.classify import classify
from investigator.dedupe import dedupe
from investigator.parsing import ParseResult, parse_output

from test_parse_scenario import fetch  # same fetch set as the M3 integration test

RENAMES = {  # every scenario name -> something unrelated; longest first so substrings don't clash
    "notification-worker": "zz-delta", "fulfillment-worker": "zz-gamma", "product-service": "zz-beta",
    "order-service": "zz-alpha", "edge-gateway": "zz-epsilon", "pricing.events": "q.one",
    "orders.events": "q.two", "fulfillment": "zzg", "notification": "zzd", "cluster-a": "c-77",
    "kafka-a:9092": "bk-9:9093", "appdb": "dbx", "db-a": "dbh-1",
}


def rename(text: str) -> str:
    for old in sorted(RENAMES, key=len, reverse=True):
        text = text.replace(old, RENAMES[old])
    return text


def signature(events):
    return Counter((e.source.value, e.component, e.level.value, e.severity.value, e.error_code) for e in events)


@pytest.fixture
def scenario(tmp_path, monkeypatch, capsys):
    res, inc = fetch(tmp_path, monkeypatch, capsys)
    return tmp_path / "work", classify(res.events), inc


def test_scenario1_classification(scenario):
    _, events, inc = scenario
    by_id = {e.event_id: e for e in events}
    assert by_id[inc.seed.event_id].error_code == "app.event_wait_timeout"
    codes = Counter(e.error_code for e in events if e.error_code)
    assert codes["kafka.broker.isr_shrink"] == 1
    assert codes["kafka.broker.request_failed"] == 2
    assert codes["kafka.producer.record_expired"] == 2
    assert codes["app.publish_failed"] == 2
    assert all(e.severity.value == "CONTEXT" for e in events if e.component == "message")
    assert not any(e.severity.value == "ANOMALY" for e in events)  # scenario 1's seed config is consistent


def test_classification_is_invariant_under_renaming(scenario):
    workdir, events, _ = scenario
    renamed = ParseResult()
    for out in FileSource(workdir).outputs():
        renamed.extend(parse_output(RawOutput(out.name, [rename(a) for a in out.argv], out.exit_code,
                                              [rename(l) for l in out.lines])))
    renamed_events = classify(dedupe(renamed.events))
    blob = "\n".join(e.message + " " + str(e.app) for e in renamed_events)
    assert not any(old in blob for old in RENAMES)  # the rename really took effect
    assert signature(renamed_events) == signature(events)
