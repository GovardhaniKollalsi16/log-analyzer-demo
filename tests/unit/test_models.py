from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from investigator.models import (
    DEFAULT_SKEW_TOLERANCE_MS,
    AnalysisBundle,
    Confidence,
    Event,
    Finding,
    Ids,
    Level,
    RawRecord,
    Source,
    to_jsonable,
)

UTC = timezone.utc


def make_event(event_id: str = "ev-1", ts: datetime | None = None) -> Event:
    return Event(
        event_id=event_id,
        source=Source.APP,
        service="svc-x",
        level=Level.ERROR,
        message="something failed",
        ts_raw="2026-01-01T00:00:00Z",
        ts_utc=ts if ts is not None else datetime(2026, 1, 1, tzinfo=UTC),
        ids=Ids(correlation_id="c-1"),
        raw_refs=[RawRecord(Source.APP, "mocklogs ...", 1, "raw line")],
    )


def test_level_ordering_and_error_flag():
    assert Level.DEBUG.rank < Level.INFO.rank < Level.WARN.rank < Level.ERROR.rank < Level.CRITICAL.rank
    assert Level.ERROR.is_error and Level.CRITICAL.is_error
    assert not Level.WARN.is_error


def test_confidence_is_categorical_and_ordered():
    assert [c.value for c in Confidence] == ["INSUFFICIENT", "LOW", "MEDIUM", "HIGH"]
    assert Confidence.LOW.at_most(Confidence.MEDIUM)
    assert Confidence.MEDIUM.at_most(Confidence.MEDIUM)
    assert not Confidence.HIGH.at_most(Confidence.MEDIUM)


def test_ids_present_only_returns_set_ids():
    assert Ids(trace_id="t-1", message_id="m-1").present() == {"trace_id": "t-1", "message_id": "m-1"}
    assert Ids().is_empty()


def test_event_requires_utc_aware_timestamp():
    with pytest.raises(ValueError, match="UTC"):
        make_event(ts=datetime(2026, 1, 1))  # naive
    with pytest.raises(ValueError, match="UTC"):
        make_event(ts=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2))))


def test_event_allows_missing_timestamp_and_rejects_empty_id():
    ev = make_event()
    ev_no_ts = Event(**{**ev.__dict__, "ts_utc": None})
    assert ev_no_ts.ts_utc is None
    with pytest.raises(ValueError):
        make_event(event_id="")


def test_finding_must_cite_events():
    with pytest.raises(ValueError, match="at least one event_id"):
        Finding(finding_id="f-1", detector="d", kind="k", event_ids=[], summary="s")


def test_bundle_defaults_and_event_ids():
    bundle = AnalysisBundle(bundle_id="b-1", events=[make_event("ev-1"), make_event("ev-2")])
    assert bundle.skew_tolerance_ms == DEFAULT_SKEW_TOLERANCE_MS == 60_000
    assert bundle.confidence_cap is Confidence.INSUFFICIENT
    assert bundle.event_ids() == {"ev-1", "ev-2"}


def test_to_jsonable_produces_json_with_utc_z_timestamps():
    bundle = AnalysisBundle(bundle_id="b-1", events=[make_event()], sources_queried=[Source.APP])
    data = json.loads(json.dumps(to_jsonable(bundle)))
    ev = data["events"][0]
    assert ev["ts_utc"] == "2026-01-01T00:00:00Z"
    assert ev["level"] == "ERROR" and ev["source"] == "app"
    assert ev["ids"]["correlation_id"] == "c-1"
    assert data["sources_queried"] == ["app"]
    assert data["confidence_cap"] == "INSUFFICIENT"


def test_to_jsonable_refuses_naive_datetime():
    with pytest.raises(ValueError, match="naive"):
        to_jsonable(datetime(2026, 1, 1))
