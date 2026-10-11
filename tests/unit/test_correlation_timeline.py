"""M6 unit tests: linking rules and the timeline, on hand-made events."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from investigator.correlation import correlate
from investigator.models import (AppTopology, Event, Ids, Incident, KafkaRef, Level, LinkKind, Location, Seed,
                                 Source)
from investigator.timeline import build_timeline

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_n = iter(range(100_000))


def at(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def app_ev(s, app, msg="m", cid=None, thread=None, instance="i-0", keys=None, logger="x.Thing", level=Level.INFO,
           error=None):
    return Event(event_id=f"ev-{next(_n)}", source=Source.APP, level=level, message=msg, ts_raw="", ts_utc=at(s),
                 app=app, cluster="c", namespace="n", instance=instance if thread else None, thread=thread,
                 logger=logger, ids=Ids(correlation_id=cid), keys=keys or {},
                 attrs={"error": error} if error else {})


def kafka_ev(s, component, msg, topic="t", partitions=(), logger="k.Logger", client=None, keys=None, partition=None,
             offset=None, producer=None, cid=None):
    attrs = {"partitions": list(partitions)}
    if client:
        attrs["client_id"] = client
    return Event(event_id=f"ev-{next(_n)}", source=Source.KAFKA, level=Level.WARN, message=msg, ts_raw="",
                 ts_utc=at(s), component=component, logger=logger, keys=keys or {},
                 app=producer, ids=Ids(correlation_id=cid),
                 kafka=KafkaRef(topic=topic, partition=partition, offset=offset, client_id=client,
                                producer_app=producer), attrs=attrs)


def incident(seed_ev, key="order_id", topics=("t",)):
    seed = Seed(event_id=seed_ev.event_id, app=seed_ev.app, ts_utc=seed_ev.ts_utc, keys=dict(seed_ev.keys),
                business_key=key if seed_ev.keys.get(key) else None, correlation_id=seed_ev.ids.correlation_id)
    return Incident(seed=seed, seed_event=seed_ev, app=Location("c", "n"), kafka_topics=list(topics))


def kinds(result, a, b):
    return {l.kind for l in result.links if {l.a, l.b} == {a.event_id, b.event_id}}


# --- EXACT_ID ------------------------------------------------------------------------------

def test_correlation_ids_link_within_an_app_never_across_apps():
    a1, a2 = app_ev(0, "svc-a", cid="c-1"), app_ev(1, "svc-a", cid="c-1")
    b1 = app_ev(2, "svc-b", cid="c-1")  # same ID string, different app
    r = correlate([a1, a2, b1], incident(a2), None)
    assert kinds(r, a1, a2) == {LinkKind.EXACT_ID}
    assert not any(b1.event_id in (l.a, l.b) for l in r.links)


def test_kafka_message_header_id_links_to_its_producer_app_only():
    prod = app_ev(0, "svc-p", cid="c-7")
    msg = kafka_ev(0.5, "message", "message t-0@1", producer="svc-p", cid="c-7", partition=0, offset=1)
    other = app_ev(1, "svc-q", cid="c-7")
    r = correlate([prod, msg, other], incident(prod), None)
    assert kinds(r, prod, msg) == {LinkKind.EXACT_ID}
    assert not any(other.event_id in (l.a, l.b) for l in r.links)


# --- THREAD_LOCAL ---------------------------------------------------------------------------

def test_two_requests_interleaved_on_one_thread_are_not_merged():
    a1 = app_ev(0, "svc-a", cid="c-A", thread="w-1")
    idless_a = app_ev(1, "svc-a", "retrying", thread="w-1")          # belongs to A's unit of work
    b1 = app_ev(2, "svc-a", cid="c-B", thread="w-1")                 # thread switched to request B
    r = correlate([a1, idless_a, b1], incident(a1), None)
    assert kinds(r, a1, idless_a) == {LinkKind.THREAD_LOCAL}
    assert not kinds(r, idless_a, b1)
    groups = {e: g.group_id for g in r.groups for e in g.event_ids}
    assert groups.get(b1.event_id) != groups[a1.event_id]


def test_thread_segment_breaks_after_a_one_minute_gap():
    a1 = app_ev(0, "svc-a", cid="c-A", thread="w-1")
    late = app_ev(61, "svc-a", "retrying", thread="w-1")
    assert not kinds(correlate([a1, late], incident(a1), None), a1, late)


def test_same_thread_name_in_two_apps_or_instances_is_not_linked():
    a = app_ev(0, "svc-a", cid="c-A", thread="w-1")
    b = app_ev(1, "svc-b", "x", thread="w-1")
    c = app_ev(2, "svc-a", "y", thread="w-1", instance="i-1")
    r = correlate([a, b, c], incident(a), None)
    assert not r.links


# --- BUSINESS_KEY ---------------------------------------------------------------------------

def test_business_key_links_across_apps_inside_the_window_only():
    seed = app_ev(0, "svc-a", keys={"order_id": "o-1"}, level=Level.ERROR)
    near = app_ev(-60, "svc-b", keys={"order_id": "o-1"})
    far = app_ev(-3600, "svc-c", keys={"order_id": "o-1"})  # an hour earlier: outside the -10 min window
    r = correlate([seed, near, far], incident(seed), None)
    assert kinds(r, near, seed) == {LinkKind.BUSINESS_KEY}
    assert not any(far.event_id in (l.a, l.b) for l in r.links)


def test_only_the_seed_business_key_links():
    seed = app_ev(0, "svc-a", keys={"order_id": "o-1", "product_id": "p-1"})
    other_order_same_product = app_ev(5, "svc-b", keys={"order_id": "o-2", "product_id": "p-1"})
    r = correlate([seed, other_order_same_product], incident(seed), None)
    assert not r.links  # R22: a shared product_id doesn't link different orders when the key is order_id


# --- RESOURCE & SAME_OCCURRENCE ---------------------------------------------------------------

def test_resource_links_log_records_naming_the_same_topic_partition_but_not_messages():
    seed = app_ev(0, "svc-a", "publish failed", level=Level.ERROR,
                  error={"type": "E", "message": "Expiring 1 record(s) for t-2: 20000 ms"})
    broker = kafka_ev(-30, "broker", "[Partition t-2 broker=1] Shrinking ISR", partitions=[2])
    other_partition = kafka_ev(-20, "broker", "[Partition t-1 broker=1] Shrinking ISR", partitions=[1])
    msg = kafka_ev(-10, "message", "message t-2@5", partition=2, offset=5)
    r = correlate([seed, broker, other_partition, msg], incident(seed), None)
    assert kinds(r, broker, seed) == {LinkKind.RESOURCE}
    assert r.resources[seed.event_id] == ["t-2"]
    assert not any(e.event_id in (l.a, l.b) for l in r.links for e in (other_partition, msg))


def test_same_occurrence_pairs_a_client_line_seen_in_two_sources():
    text = "[Producer clientId=p-1] Got error produce response, retrying (2 attempts left)"
    in_app = app_ev(10, "svc-p", text, logger="k.Sender")
    in_kafka = kafka_ev(10.4, "producer", text, logger="k.Sender", client="p-1")  # the same line, moments apart
    unrelated = kafka_ev(10.5, "producer", "something else", logger="k.Sender", client="p-1")
    later_repeat = kafka_ev(30, "producer", text, logger="k.Sender", client="p-1")  # same text, a later occurrence
    r = correlate([in_app, in_kafka, unrelated, later_repeat], incident(in_app), None)
    assert r.copies == {in_kafka.event_id: in_app.event_id}
    assert kinds(r, in_app, in_kafka) == {LinkKind.SAME_OCCURRENCE}


def test_client_lines_are_attributed_only_via_declared_ids():
    k = kafka_ev(0, "producer", "x", client="p-1")
    topo = AppTopology(app="svc-a", client_ids={"p-1": "svc-p"})
    seed = app_ev(1, "svc-a")
    r = correlate([k, seed], incident(seed), topo)
    assert next(e for e in r.events if e.event_id == k.event_id).app == "svc-p"
    r2 = correlate([k, seed], incident(seed), AppTopology(app="svc-a"))
    assert next(e for e in r2.events if e.event_id == k.event_id).app is None


# --- timeline ----------------------------------------------------------------------------------

def test_timeline_orders_by_utc_timestamp_only():
    """D30: no clock adjustment. A message consumed 60 s after it was produced stays 60 s later."""
    produced = app_ev(0, "svc-p", "published", cid="c-1")
    consumed = kafka_ev(60, "message", "message t-0@1", producer="svc-p", cid="c-1", partition=0, offset=1)
    broker = kafka_ev(-5, "broker", "[Partition t-0] Shrinking ISR", partitions=[0])
    config = Event(event_id="cfg-1", source=Source.APP_CONFIG, level=Level.INFO, message="k=v", ts_raw="", ts_utc=None,
                   app="svc-p", attrs={"key": "k", "value": "v"})
    tl = build_timeline([consumed, config, produced, broker])
    assert [(t.event_id, t.ts_utc) for t in tl.entries] == [
        (broker.event_id, at(-5)), (produced.event_id, at(0)), (consumed.event_id, at(60))]  # config: untimed


def test_timeline_can_be_restricted_to_a_group():
    a, b, c = app_ev(0, "svc-a", "a"), app_ev(1, "svc-a", "b"), app_ev(2, "svc-a", "c")
    assert [t.event_id for t in build_timeline([a, b, c], only=[c.event_id, a.event_id]).entries] == \
        [a.event_id, c.event_id]


def test_timeline_ties_are_deterministic_and_independent_of_input_order():
    same_time = [app_ev(5, "svc-a", "x"), kafka_ev(5, "broker", "y"), app_ev(5, "svc-b", "z"), app_ev(1, "svc-q", "q")]
    order1 = [t.event_id for t in build_timeline(same_time).entries]
    shuffled = same_time[:]
    random.Random(3).shuffle(shuffled)
    assert [t.event_id for t in build_timeline(shuffled).entries] == order1
    assert order1[0] == same_time[3].event_id  # earliest first; app before kafka at equal times
