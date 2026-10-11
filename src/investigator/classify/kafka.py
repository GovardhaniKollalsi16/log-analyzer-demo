"""Kafka (PROPOSAL §2.3): producer / broker / consumer logs, consumer-group lag, messages.

Log lines: ordered rule table, the first match wins. Lag: classified per (group, topic,
partition) across timed samples, in `classify_lag`. Messages are always CONTEXT;
their presence or absence is evidence for detectors (M7), not an error by itself.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Tuple

from investigator.classify.rules import ERROR_LEVELS, Rule, Thresholds, rx
from investigator.models import Event, Level, Severity

E, S = Severity.ERROR, Severity.SYMPTOM
P, B, C = ("producer",), ("broker",), ("consumer",)

RULES = [
    # --- producer ----------------------------------------------------------------
    Rule("kafka.producer.record_expired", E, "Record expired before delivery (delivery timeout passed)",
         components=P, pattern=rx(r"expiring \d+ record|delivery\.timeout")),
    Rule("kafka.producer.buffer_exhausted", E, "Producer send buffer exhausted",
         components=P, pattern=rx(r"buffer ?exhausted")),
    Rule("kafka.producer.not_authorized", E, "Producer not authorized for the topic",
         components=P, pattern=rx(r"authorizationexception|not authorized")),
    Rule("kafka.producer.delivery_failed", E, "Delivery failed after retries",
         components=P, levels=ERROR_LEVELS),
    Rule("kafka.producer.retry", S, "One send retry (attempts left)",
         components=P, pattern=rx(r"retrying|attempts left")),
    Rule("kafka.producer.metadata", S, "Recoverable metadata / leadership error",
         components=P, pattern=rx(r"not_leader|leader_not_available|metadata")),
    # --- broker ------------------------------------------------------------------
    Rule("kafka.broker.partition_offline", E, "Partition offline / no leader",
         components=B, pattern=rx(r"offline|no leader|leader is not available")),
    Rule("kafka.broker.request_failed", E, "Broker could not complete a request for the partition",
         components=B, pattern=rx(r"timed out waiting for in-sync replicas|not_?enough_?replicas|rejected")),
    Rule("kafka.broker.isr_shrink", S, "In-sync replica set shrank",
         components=B, pattern=rx(r"shrinking isr|isr shrink")),
    Rule("kafka.broker.under_replicated", S, "Partition under-replicated",
         components=B, pattern=rx(r"under-?replicated")),
    Rule("kafka.broker.leader_election", S, "Leader election / leader change",
         components=B, pattern=rx(r"leader election|elected as leader|leader change")),
    Rule("kafka.broker.error", E, "Any other broker ERROR",
         components=B, levels=ERROR_LEVELS),
    # --- consumer ----------------------------------------------------------------
    Rule("kafka.consumer.deserialization_failed", E, "Could not deserialize a record",
         components=C, pattern=rx(r"deserializ|serializationexception")),
    Rule("kafka.consumer.commit_failed", E, "Offset commit failed",
         components=C, pattern=rx(r"commitfailed|commit failed|failed to commit")),
    Rule("kafka.consumer.dead_lettered", E, "Record sent to a dead-letter topic",
         components=C, pattern=rx(r"dead.?letter|\bdlq\b|\bdlt\b")),
    Rule("kafka.consumer.poll_timeout", E, "Max poll interval exceeded / consumer left the group",
         components=C, pattern=rx(r"max\.poll\.interval|leaving group|kicked out")),
    Rule("kafka.consumer.processing_failed", E, "Exception while processing a record",
         components=C, levels=ERROR_LEVELS),
    Rule("kafka.consumer.rebalance", S, "Consumer group rebalance",
         components=C, pattern=rx(r"rebalanc|revoking previously assigned")),
    Rule("kafka.consumer.warning", S, "Any other consumer WARN",
         components=C, levels=(Level.WARN,)),
]


def classify_lag(events: List[Event], t: Thresholds) -> List[Event]:
    """Lag rows: ERROR if lag above threshold AND growing across consecutive timed samples,
    or the committed offset is stuck while the log end grows; SYMPTOM if merely above
    threshold. Untimed snapshots (no sample time) can only ever be SYMPTOM."""
    series: Dict[Tuple[str, str, int], List[Event]] = {}
    for ev in events:
        k = ev.kafka
        series.setdefault((k.group or "", k.topic, k.partition or 0), []).append(ev)
    out: Dict[str, Event] = {}
    for rows in series.values():
        timed = sorted((e for e in rows if e.ts_utc is not None), key=lambda e: e.ts_utc)
        lags = [e.attrs["lag"] for e in timed]
        rising = sum(1 for a, b in zip(lags, lags[1:]) if b > a)
        stuck = len(timed) >= 2 and len({e.attrs["current_offset"] for e in timed}) == 1 and \
            timed[-1].attrs["log_end_offset"] > timed[0].attrs["log_end_offset"]
        for ev in rows:
            code = sev = None
            if ev.ts_utc is not None and stuck and ev.attrs["lag"] > 0:
                code, sev = "kafka.lag.partition_stuck", Severity.ERROR
            elif ev.ts_utc is not None and ev.attrs["lag"] > t.lag_threshold and rising >= t.lag_growth_samples - 1 \
                    and len(timed) >= t.lag_growth_samples:
                code, sev = "kafka.lag.growing", Severity.ERROR
            elif ev.attrs["lag"] > t.lag_threshold:
                code, sev = "kafka.lag.high", Severity.SYMPTOM
            out[ev.event_id] = replace(ev, severity=sev, error_code=code) if code else ev
    return [out[e.event_id] for e in events]


LAG_RULES_DOC = [
    ("kafka.lag.partition_stuck", "ERROR", "Committed offset unchanged across timed samples while the log end grows, with lag > 0"),
    ("kafka.lag.growing", "ERROR", "Lag > threshold and rising across >= `lag_growth_samples` consecutive timed samples"),
    ("kafka.lag.high", "SYMPTOM", "Lag > threshold, not growing (or untimed snapshot)"),
]
