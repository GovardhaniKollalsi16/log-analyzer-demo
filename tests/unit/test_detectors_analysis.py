"""M7 unit tests: each detector (positive + negative), factors, the ceiling table, chains and rivals.
Hand-made, generic events; no scenario data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from investigator.adapters.base import RawOutput
from investigator.analysis import _ceiling, _coverage, _precedence, build_bundle
from investigator.classify import classify
from investigator.correlation import correlate
from investigator.detectors import (Context, config_vs_observed, db_error_burst, delivery_failure_chain,
                                    first_error_per_app, missing_message, poison_message, retry_exhaustion)
from investigator.models import (AppTopology, Confidence, ConfidenceFactor, CoverageGap, Event, FactorName,
                                 FactorValue, GapReason, Ids, Incident, KafkaRef, Level, Location, Seed, Severity,
                                 Source)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_n = iter(range(100_000))
V = FactorValue


def at(s):
    return T0 + timedelta(seconds=s)


def ev(s, source, msg, *, app=None, level=Level.INFO, component=None, sev=Severity.CONTEXT, code=None, cid=None,
       keys=None, error=None, topic=None, partition=None, client=None, attrs=None):
    a = dict(attrs or {})
    if error:
        a["error"] = error
    if client:
        a["client_id"] = client
    return Event(event_id=f"ev-{next(_n)}", source=source, level=level, message=msg, ts_raw="", ts_utc=at(s),
                 app=app, component=component, logger="x.L", severity=sev, error_code=code,
                 ids=Ids(correlation_id=cid), keys=keys or {}, attrs=a,
                 kafka=KafkaRef(topic=topic, partition=partition, client_id=client) if topic else None)


def ctx_for(events, seed, topics=("t",), topology=None, outputs=()):
    inc = Incident(seed=Seed(event_id=seed.event_id, app=seed.app, ts_utc=seed.ts_utc, keys=dict(seed.keys),
                             business_key="order_id" if "order_id" in seed.keys else None,
                             correlation_id=seed.ids.correlation_id),
                   seed_event=seed, app=Location("c", "n"), kafka_topics=list(topics))
    return Context(inc, correlate(events, inc, topology), topology, list(outputs))


SEED = lambda s=0, **kw: ev(s, Source.APP, kw.pop("msg", "Timed out waiting for reply"), app="svc-a", level=Level.ERROR,  # noqa: E731
                            sev=Severity.ERROR, code="app.event_wait_timeout", cid="c-1",
                            keys={"order_id": "o-1"}, **kw)


# --- D-1 retry_exhaustion -----------------------------------------------------------------

def retries(n, give_up=True, start=-30):
    out = [ev(start + i, Source.KAFKA, f"retrying #{i}", component="producer", sev=Severity.SYMPTOM,
              code="kafka.producer.retry", client="p-1", topic="t") for i in range(n)]
    if give_up:
        out.append(ev(start + n, Source.KAFKA, "Expiring 1 record(s) for t-0", component="producer",
                      level=Level.ERROR, sev=Severity.ERROR, code="kafka.producer.record_expired", client="p-1", topic="t"))
    return out


@pytest.mark.parametrize("n,give_up,fires", [(2, True, True), (3, True, True), (1, True, False), (3, False, False)])
def test_retry_exhaustion(n, give_up, fires):
    seed = SEED()
    found = retry_exhaustion(ctx_for(retries(n, give_up) + [seed], seed))
    assert bool(found) is fires
    if fires:
        assert found[0].attrs["retries"] == n and found[0].attrs["key"] == "client:p-1"


# --- D-2 delivery_failure_chain -------------------------------------------------------------

def test_delivery_failure_chain_needs_broker_and_client_errors_on_the_same_partition():
    seed = SEED(error={"type": "E", "message": "Expiring 1 record(s) for t-2"})
    broker = ev(-60, Source.KAFKA, "[Partition t-2] Shrinking ISR", component="broker", level=Level.WARN,
                sev=Severity.SYMPTOM, code="kafka.broker.isr_shrink", topic="t", attrs={"partitions": [2]})
    (f,) = delivery_failure_chain(ctx_for([broker, seed], seed))
    assert f.attrs["resource"] == "t-2" and set(f.event_ids) == {broker.event_id, seed.event_id}
    other = ev(-60, Source.KAFKA, "[Partition t-1] Shrinking ISR", component="broker", level=Level.WARN,
               sev=Severity.SYMPTOM, code="kafka.broker.isr_shrink", topic="t", attrs={"partitions": [1]})
    assert delivery_failure_chain(ctx_for([other, seed], seed)) == []


# --- D-3 missing_message -----------------------------------------------------------------------

def search(value, found_lines=()):
    return RawOutput("001-x", ["mocklogs", "kafka-console-consumer", "--bootstrap-server", "k:9092", "--topic", "t",
                               "--partition", "0", "--offset", "1", "--grep", value, "--save-dir", "/w"], 0,
                     ["# MOCK DATA", *found_lines, "Processed a total of 0 messages"])


def test_missing_message_fires_on_empty_searches_plus_a_key_failure():
    seed = SEED()
    (f,) = missing_message(ctx_for([seed], seed, outputs=[search("o-1")]))
    assert f.event_ids == [seed.event_id] and f.attrs["absence"][0]["topic"] == "t"


def test_missing_message_not_when_the_message_was_found_or_never_searched():
    seed = SEED()
    assert missing_message(ctx_for([seed], seed, outputs=[search("o-1", ["CreateTime:1\t{\"order_id\":\"o-1\"}"])])) == []
    assert missing_message(ctx_for([seed], seed, outputs=[])) == []


# --- D-4 poison_message ------------------------------------------------------------------------

@pytest.mark.parametrize("count,fires", [(3, True), (2, False)])
def test_poison_message(count, fires):
    seed = SEED()
    fails = [ev(-30 + i, Source.KAFKA, "Exception while processing record at offset 42", component="consumer",
                level=Level.ERROR, sev=Severity.ERROR, code="kafka.consumer.processing_failed", topic="t", partition=0)
             for i in range(count)]
    assert bool(poison_message(ctx_for(fails + [seed], seed))) is fires


# --- D-5 db_error_burst ------------------------------------------------------------------------

@pytest.mark.parametrize("count,fires", [(3, True), (2, False)])
def test_db_error_burst(count, fires):
    seed = SEED()
    errors = [ev(-20 + i, Source.DB, "deadlock detected", app="svc-a", level=Level.ERROR, sev=Severity.ERROR,
                 code="db.deadlock", attrs={"db": "d"}) for i in range(count)]
    assert bool(db_error_burst(ctx_for(errors + [seed], seed))) is fires


# --- D-6 config_vs_observed ------------------------------------------------------------------

def cfg(app, key, value):
    return Event(event_id=f"cfg-{next(_n)}", source=Source.APP_CONFIG, level=Level.INFO, message=f"{key}={value}",
                 ts_raw="", ts_utc=None, app=app, attrs={"key": key, "value": value})


def test_config_anomaly_plus_errors_it_explains():
    seed = ev(0, Source.APP, "DB call failed: too many clients", app="svc-a", level=Level.ERROR,
              sev=Severity.ERROR, code="app.db_call_failed", cid="c-1", keys={"order_id": "o-1"})
    config = classify([cfg("svc-a", "db.pool.size", "4"), cfg("svc-a", "worker.threads", "16")])
    found = config_vs_observed(ctx_for(config + [seed], seed))
    assert found and all(f.attrs["key"] in ("db.pool.size", "worker.threads") for f in found)


def test_configured_timeout_matching_the_observed_timeout():
    seed = SEED(error={"type": "E", "message": "no reply within 5000 ms"})
    assert config_vs_observed(ctx_for([cfg("svc-a", "reply.timeout.ms", "5000"), seed], seed))
    assert config_vs_observed(ctx_for([cfg("svc-a", "reply.timeout.ms", "7000"), seed], seed)) == []


# --- D-7 first_error_per_app ------------------------------------------------------------------

def test_first_error_per_app():
    seed = SEED()
    earlier = ev(-10, Source.APP, "boom", app="svc-a", level=Level.ERROR, sev=Severity.ERROR, code="app.exception",
                 cid="c-1")
    (f,) = first_error_per_app(ctx_for([earlier, seed], seed))
    assert f.event_ids == [earlier.event_id]


# --- factors & ceiling --------------------------------------------------------------------------

def facs(link, cov, prec, comp):
    return [ConfidenceFactor(FactorName.ID_LINKAGE, link, ""), ConfidenceFactor(FactorName.TRAVERSAL_COVERAGE, cov, ""),
            ConfidenceFactor(FactorName.TEMPORAL_PRECEDENCE, prec, ""),
            ConfidenceFactor(FactorName.COMPETING_HYPOTHESES, comp, "")]


@pytest.mark.parametrize("factors,expected", [
    ((V.STRONG, V.STRONG, V.STRONG, V.STRONG), Confidence.HIGH),
    ((V.PARTIAL, V.STRONG, V.STRONG, V.STRONG), Confidence.MEDIUM),
    ((V.STRONG, V.PARTIAL, V.STRONG, V.STRONG), Confidence.MEDIUM),
    ((V.STRONG, V.STRONG, V.STRONG, V.PARTIAL), Confidence.MEDIUM),
    ((V.WEAK, V.STRONG, V.STRONG, V.STRONG), Confidence.LOW),
    ((V.STRONG, V.WEAK, V.STRONG, V.STRONG), Confidence.LOW),
    ((V.STRONG, V.STRONG, V.WEAK, V.STRONG), Confidence.LOW),
    ((V.STRONG, V.STRONG, V.STRONG, V.WEAK), Confidence.LOW),
    ((V.ABSENT, V.STRONG, V.STRONG, V.STRONG), Confidence.INSUFFICIENT),
    ((V.STRONG, V.ABSENT, V.STRONG, V.STRONG), Confidence.INSUFFICIENT),
    ((V.STRONG, V.STRONG, V.ABSENT, V.STRONG), Confidence.INSUFFICIENT),
    ((V.PARTIAL, V.WEAK, V.STRONG, V.STRONG), Confidence.LOW),  # the lowest rule wins
])
def test_ceiling_table(factors, expected):
    assert _ceiling(facs(*factors)) is expected


def gap(component, target, reason=GapReason.MISSING_INPUT):
    return CoverageGap(component, target, reason)


@pytest.mark.parametrize("gaps,dbs,expected", [
    ([], [], V.STRONG),
    ([gap(Source.DB, "db")], [], V.STRONG),                         # no DB declared: a missing db: line is irrelevant
    ([gap(Source.DB, "db")], ["d"], V.PARTIAL),                     # declared DB not collected
    ([gap(Source.APP, "down-1")], [], V.PARTIAL),                   # downstream app
    ([gap(Source.APP, "up-1")], [], V.WEAK),                        # upstream app
    ([gap(Source.KAFKA, "kafka")], [], V.WEAK),
    ([gap(Source.APP_CONFIG, "svc-a-config", GapReason.ACCESS_DENIED)], [], V.WEAK),
    ([gap(Source.APP, "svc-a")], [], V.ABSENT),                     # the seed app's own logs
])
def test_coverage(gaps, dbs, expected):
    seed = SEED()
    inc = ctx_for([seed], seed).incident
    topo = AppTopology(app="svc-a", upstream_apps=["up-1"], downstream_apps=["down-1"], databases=dbs)
    assert _coverage(gaps, inc, topo).value is expected


def test_precedence():
    seed = SEED()
    before, after = SEED(-5), SEED(5)
    assert _precedence(before, [seed], seed).value is V.STRONG
    assert _precedence(after, [seed], seed).value is V.ABSENT
    assert _precedence(before, [SEED(-9), seed], seed).value is V.WEAK
    assert _precedence(cfg("svc-a", "k", "v"), [seed], seed).value is V.STRONG  # config predates the incident


# --- hypotheses ---------------------------------------------------------------------------------

def test_repeated_pattern_on_one_client_is_one_hypothesis_not_rivals():
    seed = SEED()
    events = retries(2, start=-120) + retries(2, start=-60) + [seed]
    bundle = build_bundle(ctx_for(events, seed).incident, ctx_for(events, seed).cor, None, [], [])
    assert len(bundle.hypotheses) == 1
    assert next(f for f in bundle.hypotheses[0].factors if f.name is FactorName.COMPETING_HYPOTHESES).value is V.STRONG


def test_no_findings_means_no_hypothesis_and_insufficient():
    seed = SEED()
    ctx = ctx_for([seed], seed)
    bundle = build_bundle(ctx.incident, ctx.cor, None, [], [])
    assert bundle.hypotheses == [] and bundle.confidence_cap is Confidence.INSUFFICIENT


def test_every_cited_event_is_in_the_bundle():
    seed = SEED()
    events = retries(3) + [seed]
    ctx = ctx_for(events, seed)
    bundle = build_bundle(ctx.incident, ctx.cor, None, [], [])
    ids = bundle.event_ids()
    assert all(e in ids for f in bundle.findings for e in f.event_ids)
    assert all(h.cause_event_id in ids and set(h.effect_event_ids) <= ids for h in bundle.hypotheses)
