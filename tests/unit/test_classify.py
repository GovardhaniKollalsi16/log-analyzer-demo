"""M4: per-component classification. Every rule has a positive case; edge cases pin the boundaries.

Lines are hand-written and generic, NOT copied from any scenario, so these tests check
the rules rather than one scenario's wording.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from investigator.classify import Thresholds, classify
from investigator.classify import app as app_rules
from investigator.classify import config as config_rules
from investigator.classify import db as db_rules
from investigator.classify import kafka as kafka_rules
from investigator.models import Event, KafkaRef, Level, Severity, Source

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
L = Level
_n = iter(range(10_000))


def ev(source, level, message, component=None, error=None, **kw) -> Event:
    i = next(_n)
    return Event(event_id=f"ev-{i}", source=source, level=level, message=message, ts_raw="", ts_utc=T0,
                 component=component, attrs={"error": error} if error else {}, **kw)


def app(level, msg, error=None):
    return ev(Source.APP, level, msg, error=error, app="svc-a")


def kafka(component, level, msg):
    return ev(Source.KAFKA, level, msg, component=component)


def db(level, msg):
    return ev(Source.DB, level, msg, component="db")


# (event, expected severity, expected code). One positive case per rule, at least.
CASES = [
    # --- app ---
    (app(L.ERROR, "Failed to publish order event"), "ERROR", "app.publish_failed"),
    (app(L.ERROR, "Giving up after 5 attempts"), "ERROR", "app.retries_exhausted"),
    (app(L.ERROR, "Timed out waiting for reply from billing"), "ERROR", "app.event_wait_timeout"),
    (app(L.ERROR, "Query failed", {"type": "java.sql.SQLException", "message": "x"}), "ERROR", "app.db_call_failed"),
    (app(L.ERROR, "Call to inventory timed out"), "ERROR", "app.outbound_timeout"),
    (app(L.ERROR, "NullPointerException in handler"), "ERROR", "app.exception"),
    (app(L.CRITICAL, "Out of memory"), "ERROR", "app.exception"),
    (app(L.WARN, "Retrying request (attempt 2/5)"), "SYMPTOM", "app.retry_attempt"),
    (app(L.WARN, "Circuit breaker is open for billing"), "SYMPTOM", "app.circuit_open"),
    (app(L.WARN, "Worker pool exhausted, rejecting task"), "SYMPTOM", "app.pool_saturated"),
    (app(L.INFO, "Lookup took 1200 ms (threshold 1000 ms)"), "SYMPTOM", "app.slow_call"),
    (app(L.WARN, "Disk usage at 85%"), "SYMPTOM", "app.warning"),
    # --- kafka producer ---
    (kafka("producer", L.ERROR, "Expiring 2 record(s) for t-0: 120000 ms has passed since batch creation"), "ERROR", "kafka.producer.record_expired"),
    (kafka("producer", L.ERROR, "BufferExhaustedException: Failed to allocate memory within the configured max blocking time"), "ERROR", "kafka.producer.buffer_exhausted"),
    (kafka("producer", L.ERROR, "TopicAuthorizationException: Not authorized to access topics: [t]"), "ERROR", "kafka.producer.not_authorized"),
    (kafka("producer", L.ERROR, "Error when sending message to topic t with key: null"), "ERROR", "kafka.producer.delivery_failed"),
    (kafka("producer", L.WARN, "Got error produce response on topic-partition t-1, retrying (2 attempts left). Error: REQUEST_TIMED_OUT"), "SYMPTOM", "kafka.producer.retry"),
    (kafka("producer", L.WARN, "Error while fetching metadata with correlation id 7 : {t=LEADER_NOT_AVAILABLE}"), "SYMPTOM", "kafka.producer.metadata"),
    # --- kafka broker ---
    (kafka("broker", L.ERROR, "[Controller] Partition t-3 has no leader"), "ERROR", "kafka.broker.partition_offline"),
    (kafka("broker", L.WARN, "Produce request to t-1 failed: NOT_ENOUGH_REPLICAS"), "ERROR", "kafka.broker.request_failed"),
    (kafka("broker", L.WARN, "[Partition t-2 broker=1] Shrinking ISR from 1,2,3 to 1"), "SYMPTOM", "kafka.broker.isr_shrink"),
    (kafka("broker", L.WARN, "Partition t-2 is under-replicated"), "SYMPTOM", "kafka.broker.under_replicated"),
    (kafka("broker", L.INFO, "Elected as leader for partition t-0"), "SYMPTOM", "kafka.broker.leader_election"),
    (kafka("broker", L.ERROR, "Error processing fetch request"), "ERROR", "kafka.broker.error"),
    # --- kafka consumer ---
    (kafka("consumer", L.ERROR, "SerializationException: Error deserializing key/value for partition t-0"), "ERROR", "kafka.consumer.deserialization_failed"),
    (kafka("consumer", L.ERROR, "CommitFailedException: Commit cannot be completed"), "ERROR", "kafka.consumer.commit_failed"),
    (kafka("consumer", L.WARN, "Sent record to dead-letter topic t.DLT"), "ERROR", "kafka.consumer.dead_lettered"),
    (kafka("consumer", L.WARN, "Consumer poll timeout has expired; max.poll.interval.ms exceeded"), "ERROR", "kafka.consumer.poll_timeout"),
    (kafka("consumer", L.ERROR, "Exception while processing record at offset 42"), "ERROR", "kafka.consumer.processing_failed"),
    (kafka("consumer", L.INFO, "Revoking previously assigned partitions [t-0]"), "SYMPTOM", "kafka.consumer.rebalance"),
    (kafka("consumer", L.WARN, "Offset fetch took longer than expected"), "SYMPTOM", "kafka.consumer.warning"),
    # --- db ---
    (db(L.CRITICAL, "could not connect to server: Connection refused"), "ERROR", "db.connection_refused"),
    (db(L.CRITICAL, "sorry, too many clients already"), "ERROR", "db.too_many_connections"),
    (db(L.CRITICAL, "password authentication failed for user \"u\""), "ERROR", "db.auth_failed"),
    (db(L.ERROR, "deadlock detected"), "ERROR", "db.deadlock"),
    (db(L.ERROR, "canceling statement due to statement timeout"), "ERROR", "db.statement_timeout"),
    (db(L.ERROR, "current transaction is aborted, commands ignored until end of transaction block"), "ERROR", "db.transaction_aborted"),
    (db(L.ERROR, "relation \"t\" does not exist"), "ERROR", "db.error"),
    (db(L.INFO, "duration: 812.400 ms  statement: SELECT 1"), "SYMPTOM", "db.slow_query"),
    (db(L.INFO, "process 41 still waiting for ShareLock on transaction 9 after 1000.1 ms"), "SYMPTOM", "db.lock_wait"),
    (db(L.WARN, "connection count approaching the limit"), "SYMPTOM", "db.connections_high"),
    # --- edges: no match → CONTEXT ---
    (app(L.INFO, "Health check OK"), "CONTEXT", None),
    (app(L.WARN, "Failed to publish, will retry later"), "SYMPTOM", "app.warning"),  # publish_failed needs ERROR level
    (kafka("producer", L.INFO, "Producer started"), "CONTEXT", None),
    (kafka("broker", L.INFO, "Rolled new log segment at offset 5200"), "CONTEXT", None),
    (kafka("consumer", L.INFO, "Subscribed to topic(s): t"), "CONTEXT", None),
    (db(L.INFO, "duration: 3.100 ms  statement: SELECT 1"), "CONTEXT", None),
    (db(L.INFO, "connection authorized: user=u database=d"), "CONTEXT", None),
    (ev(Source.KAFKA, L.ERROR, "message t-0@1", component="message"), "CONTEXT", None),  # messages never classified
]


@pytest.mark.parametrize("event,severity,code", CASES, ids=[c[2] or f"context-{i}" for i, c in enumerate(CASES)])
def test_rule_cases(event, severity, code):
    (out,) = classify([event])
    assert (out.severity.value, out.error_code) == (severity, code)


def test_every_rule_has_a_positive_case():
    t = Thresholds()
    all_codes = {r.error_code for r in app_rules.RULES} | {r.error_code for r in kafka_rules.RULES} | \
        {r.error_code for r in db_rules.rules(t)}
    covered = {code for _, _, code in CASES if code}
    assert all_codes - covered == set(), f"rules without a test case: {sorted(all_codes - covered)}"


def test_first_match_wins_order_publish_before_retries():
    e = app(L.ERROR, "Failed to publish event", {"type": "TimeoutException", "message": "Expiring 1 record(s) for t-0"})
    assert classify([e])[0].error_code == "app.publish_failed"


def test_thresholds_are_tunable():
    e = db(L.INFO, "duration: 300.000 ms  statement: SELECT 1")
    assert classify([e])[0].severity is Severity.CONTEXT
    assert classify([e], Thresholds(slow_query_ms=200))[0].error_code == "db.slow_query"


# --- config ------------------------------------------------------------------------------

def cfg(app_name, **data):
    """Config events for one app; `a__b__c=v` keyword means key `a.b.c`."""
    return [Event(event_id=f"cfg-{app_name}-{k}", source=Source.APP_CONFIG, level=L.INFO, message=f"{k}={v}",
                  ts_raw="", ts_utc=None, app=app_name, attrs={"key": k.replace("__", "."), "value": v})
            for k, v in data.items()]


def by_key(events):
    return {e.attrs["key"]: (e.severity.value, e.error_code) for e in classify(events)}


def test_config_invalid_value():
    out = by_key(cfg("a", http__client__timeout__ms="-5", db__pool__size="ten", kafka__consumer__topics="t"))
    assert out["http.client.timeout.ms"] == ("ANOMALY", "config.invalid_value")
    assert out["db.pool.size"] == ("ANOMALY", "config.invalid_value")
    assert out["kafka.consumer.topics"] == ("CONTEXT", None)  # not a numeric key


def test_config_pool_smaller_than_workers_flags_both_keys():
    out = by_key(cfg("a", db__pool__size="4", worker__threads="16"))
    assert out == {"db.pool.size": ("ANOMALY", "config.inconsistent"), "worker.threads": ("ANOMALY", "config.inconsistent")}
    assert by_key(cfg("b", db__pool__size="16", worker__threads="16")) == {
        "db.pool.size": ("CONTEXT", None), "worker.threads": ("CONTEXT", None)}


def test_config_retries_times_timeout_vs_poll_interval():
    bad = by_key(cfg("a", kafka__producer__retries="5", kafka__producer__request__timeout__ms="30000",
                     kafka__consumer__max__poll__interval__ms="120000"))
    assert set(bad.values()) == {("ANOMALY", "config.inconsistent")}
    ok = by_key(cfg("b", kafka__producer__retries="2", kafka__producer__request__timeout__ms="30000",
                    kafka__consumer__max__poll__interval__ms="120000"))
    assert set(ok.values()) == {("CONTEXT", None)}


def test_config_checks_are_per_app():
    out = classify(cfg("a", db__pool__size="4") + cfg("b", worker__threads="16"))
    assert all(e.severity is Severity.CONTEXT for e in out)  # pool and threads belong to different apps


def test_anomaly_reason_is_recorded():
    (pool, _) = classify(cfg("a", db__pool__size="4", worker__threads="16"))
    assert "4 < worker threads 16" in pool.attrs["anomaly"]


# --- lag ---------------------------------------------------------------------------------

def lag_row(minute, current, end, partition=0, timed=True):
    return Event(event_id=f"lag-{partition}-{minute}-{timed}", source=Source.KAFKA, level=L.INFO,
                 message=f"lag={end - current}", ts_raw="", ts_utc=T0 + timedelta(minutes=minute) if timed else None,
                 component="consumer-group",
                 kafka=KafkaRef(topic="t", partition=partition, offset=current, group="g", client_id="c-1"),
                 attrs={"current_offset": current, "log_end_offset": end, "lag": end - current})


def codes(events):
    return [(e.severity.value, e.error_code) for e in classify(events)]


def test_lag_stuck_partition_is_error():
    assert set(codes([lag_row(1, 100, 150), lag_row(2, 100, 300), lag_row(3, 100, 450)])) == {
        ("ERROR", "kafka.lag.partition_stuck")}


def test_lag_growing_above_threshold_is_error():
    assert codes([lag_row(1, 100, 250), lag_row(2, 150, 400), lag_row(3, 200, 600)])[-1] == ("ERROR", "kafka.lag.growing")


def test_lag_high_but_steady_is_symptom():
    assert set(codes([lag_row(1, 100, 300), lag_row(2, 300, 500), lag_row(3, 500, 700)])) == {
        ("SYMPTOM", "kafka.lag.high")}


def test_lag_below_threshold_is_context():
    assert set(codes([lag_row(1, 100, 150), lag_row(2, 200, 250)])) == {("CONTEXT", None)}


def test_untimed_lag_snapshot_can_only_be_symptom():
    assert codes([lag_row(0, 0, 500, timed=False)]) == [("SYMPTOM", "kafka.lag.high")]


def test_lag_series_are_per_partition():
    rows = [lag_row(1, 100, 150, 0), lag_row(2, 100, 300, 0), lag_row(1, 10, 10, 1), lag_row(2, 20, 20, 1)]
    out = {e.kafka.partition: e.error_code for e in classify(rows)}
    assert out == {0: "kafka.lag.partition_stuck", 1: None}


# --- invariants --------------------------------------------------------------------------

def test_classification_invariants_hold_for_every_case():
    out = classify([c[0] for c in CASES])
    for e in out:
        assert (e.severity is Severity.CONTEXT) == (e.error_code is None)
        assert e.severity is not Severity.ANOMALY  # only config can be ANOMALY


def test_classify_preserves_order_and_ids():
    events = [c[0] for c in CASES]
    assert [e.event_id for e in classify(events)] == [e.event_id for e in events]


def test_rule_tables_never_mention_names():
    """Rules match wording and structure only. The boundary test checks scenario vocabulary;
    this also keeps app/topic-like tokens out of the patterns."""
    import inspect
    for module in (app_rules, kafka_rules, db_rules, config_rules):
        src = inspect.getsource(module).lower()
        for token in ("-service", "-worker", ".events", "cluster-", "kafka-a"):
            assert token not in src, (module.__name__, token)
