from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from investigator.models import (
    THREAD_SEGMENT_WINDOW_MS,
    AnalysisBundle,
    AppTopology,
    Confidence,
    ConfidenceFactor,
    CoverageGap,
    Direction,
    Event,
    FactorName,
    FactorValue,
    FetchPlan,
    FetchStep,
    Finding,
    GapReason,
    Ids,
    KafkaRef,
    Level,
    LinkKind,
    RawRecord,
    Seed,
    Severity,
    Source,
    TopicSubscription,
    to_jsonable,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_event(event_id: str = "ev-1", **overrides) -> Event:
    base = dict(
        event_id=event_id,
        source=Source.APP,
        level=Level.ERROR,
        message="something failed",
        ts_raw="2026-01-01T00:00:00Z",
        ts_utc=T0,
        app="app-x",
        instance="app-x-0",
        thread="worker-1",
        severity=Severity.ERROR,
        error_code="app.exception",
        ids=Ids(correlation_id="c-1"),
        raw_refs=[RawRecord(Source.APP, "mocklogs ...", 1, "raw line")],
    )
    base.update(overrides)
    return Event(**base)


# --- enums -------------------------------------------------------------------

def test_sources_are_the_four_rev2_components():
    assert [s.value for s in Source] == ["app", "app_config", "kafka", "db"]


def test_level_ordering():
    assert Level.DEBUG.rank < Level.INFO.rank < Level.WARN.rank < Level.ERROR.rank < Level.CRITICAL.rank


def test_confidence_is_categorical_and_ordered():
    assert [c.value for c in Confidence] == ["INSUFFICIENT", "LOW", "MEDIUM", "HIGH"]
    assert Confidence.LOW.at_most(Confidence.MEDIUM)
    assert Confidence.MEDIUM.at_most(Confidence.MEDIUM)
    assert not Confidence.HIGH.at_most(Confidence.MEDIUM)


def test_rev2_enum_members():
    assert {s.value for s in Severity} == {"ERROR", "SYMPTOM", "CONTEXT", "ANOMALY"}
    assert LinkKind.THREAD_LOCAL.value == "thread_local"
    assert {r.value for r in GapReason} == {"access_denied", "auth_required", "missing_input", "not_found", "empty"}
    assert LinkKind.BUSINESS_KEY.value == "business_key"
    assert {f.value for f in FactorName} == {
        "id_linkage", "traversal_coverage", "temporal_precedence", "competing_hypotheses",
    }  # data_quality deliberately absent (Q1)


def test_tuning_defaults():
    assert THREAD_SEGMENT_WINDOW_MS == 60_000    # D17: groups one unit of work on a thread


# --- Event invariants --------------------------------------------------------

def test_event_requires_utc_aware_timestamp():
    with pytest.raises(ValueError, match="UTC"):
        make_event(ts_utc=datetime(2026, 1, 1))  # naive
    with pytest.raises(ValueError, match="UTC"):
        make_event(ts_utc=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2))))


def test_event_allows_missing_timestamp_and_rejects_empty_id():
    assert make_event(ts_utc=None).ts_utc is None
    with pytest.raises(ValueError):
        make_event(event_id="")


def test_error_code_present_exactly_when_not_context():
    make_event(severity=Severity.CONTEXT, error_code=None)
    make_event(severity=Severity.SYMPTOM, error_code="app.retry_attempt")
    with pytest.raises(ValueError, match="error_code"):
        make_event(severity=Severity.ERROR, error_code=None)
    with pytest.raises(ValueError, match="error_code"):
        make_event(severity=Severity.CONTEXT, error_code="app.exception")


def test_classification_via_replace_rechecks_invariants():
    ev = make_event(severity=Severity.CONTEXT, error_code=None)
    classified = replace(ev, severity=Severity.ERROR, error_code="app.retries_exhausted")
    assert classified.severity is Severity.ERROR
    with pytest.raises(ValueError):
        replace(ev, severity=Severity.ERROR)  # forgot the code


def test_anomaly_only_for_app_config():
    make_event(source=Source.APP_CONFIG, severity=Severity.ANOMALY, error_code="config.inconsistent",
               instance=None, thread=None)
    with pytest.raises(ValueError, match="ANOMALY"):
        make_event(severity=Severity.ANOMALY, error_code="config.inconsistent")


def test_thread_requires_app_and_instance():
    with pytest.raises(ValueError, match="thread"):
        make_event(instance=None)
    with pytest.raises(ValueError, match="thread"):
        make_event(app=None)
    make_event(thread=None, instance=None)  # an event without a thread is fine


def test_kafka_event_carries_kafka_ref():
    ev = make_event(
        source=Source.KAFKA, component="consumer", instance=None, thread=None,
        severity=Severity.ERROR, error_code="kafka.consumer.processing_failed",
        kafka=KafkaRef(topic="t-1", partition=3, offset=42, group="g-1", producer_app="app-up"),
    )
    assert ev.kafka.producer_app == "app-up"


# --- traversal models --------------------------------------------------------

def test_seed_requires_app_and_utc():
    seed = Seed(event_id="ev-1", app="app-x", ts_utc=T0, thread="worker-1", correlation_id="c-1")
    assert seed.app == "app-x"
    with pytest.raises(ValueError, match="name the application"):
        Seed(event_id="ev-1", app="", ts_utc=T0)
    with pytest.raises(ValueError, match="UTC"):
        Seed(event_id="ev-1", app="app-x", ts_utc=datetime(2026, 1, 1))


def test_fetch_step_and_plan_invariants():
    step = FetchStep(order=1, component=Source.KAFKA, target="t-1",
                     argv=["mocklogs", "kafka-consumer-groups", "--describe", "--group", "g-1"],
                     reason="lag for the seed app's consumer group", direction=Direction.SEED)
    assert FetchPlan(steps=[step]).done is False
    with pytest.raises(ValueError, match="argv"):
        FetchStep(order=1, component=Source.APP, target="x", argv=[], reason="r")
    with pytest.raises(ValueError, match="why it stopped"):
        FetchPlan(done=True)
    assert FetchPlan(done=True, stop_reason="no remaining fetches").done


def test_coverage_gap_supports_auth_required():
    gap = CoverageGap(component=Source.KAFKA, target="t-1", reason=GapReason.AUTH_REQUIRED,
                      detail="user declined to re-authenticate")
    assert to_jsonable(gap)["reason"] == "auth_required"


# --- findings / bundle -------------------------------------------------------

def test_finding_must_cite_events():
    with pytest.raises(ValueError, match="at least one event_id"):
        Finding(finding_id="f-1", detector="d", kind="k", event_ids=[], summary="s")


def test_bundle_has_rev2_fields_and_no_parse_issues():
    names = {f.name for f in fields(AnalysisBundle)}
    assert {"seed", "topology", "traversal", "coverage_gaps"} <= names
    assert "parse_issues" not in names  # Q1


def test_bundle_defaults_and_event_ids():
    bundle = AnalysisBundle(bundle_id="b-1", events=[make_event("ev-1"), make_event("ev-2")])
    assert bundle.confidence_cap is Confidence.INSUFFICIENT
    assert bundle.event_ids() == {"ev-1", "ev-2"}


def test_to_jsonable_full_bundle_round_trips_through_json():
    bundle = AnalysisBundle(
        bundle_id="b-1",
        seed=Seed(event_id="ev-1", app="app-x", ts_utc=T0, correlation_id="c-1"),
        topology=AppTopology(app="app-x", consumes=[TopicSubscription("t-in", "g-1")],
                             produces=["t-out"], databases=["db-1"], limits={"retries": "10"}),
        traversal=[FetchStep(order=1, component=Source.APP_CONFIG, target="app-x",
                             argv=["mocklogs", "kubectl", "get", "configmap", "app-x-config"],
                             reason="seed app config")],
        coverage_gaps=[CoverageGap(Source.APP_CONFIG, "app-y", GapReason.ACCESS_DENIED)],
        events=[make_event()],
        factors=[ConfidenceFactor(FactorName.ID_LINKAGE, FactorValue.STRONG, "shared correlation ID")],
    )
    data = json.loads(json.dumps(to_jsonable(bundle)))
    ev = data["events"][0]
    assert ev["ts_utc"] == "2026-01-01T00:00:00Z"
    assert ev["severity"] == "ERROR" and ev["error_code"] == "app.exception"
    assert ev["thread"] == "worker-1" and ev["source"] == "app"
    assert data["seed"]["ts_utc"] == "2026-01-01T00:00:00Z"
    assert data["topology"]["consumes"] == [{"topic": "t-in", "group": "g-1"}]
    assert data["coverage_gaps"][0]["reason"] == "access_denied"
    assert data["factors"][0]["name"] == "id_linkage"


def test_to_jsonable_refuses_naive_datetime():
    with pytest.raises(ValueError, match="naive"):
        to_jsonable(datetime(2026, 1, 1))


# --- M3 model additions ----------------------------------------------------------

def test_event_carries_location_logger_and_business_keys():
    ev = make_event(cluster="c-1", namespace="ns", logger="x.OrderThing", keys={"order_id": "o-1"})
    data = to_jsonable(ev)
    assert data["cluster"] == "c-1" and data["keys"] == {"order_id": "o-1"} and data["logger"] == "x.OrderThing"


def test_incident_model_defaults_mean_no_input():
    from investigator.models import Incident, Location
    seed = Seed(event_id="ev-1", app="app-x", ts_utc=T0, keys={"order_id": "o-1"}, business_key="order_id")
    inc = Incident(seed=seed, seed_event=make_event())
    assert inc.app is None and inc.kafka_bootstrap is None and inc.db_host is None and not inc.related_apps
    inc.related_apps["app-y"] = Location("c-1", "ns")
    assert to_jsonable(inc)["related_apps"]["app-y"] == {"cluster": "c-1", "namespace": "ns"}
