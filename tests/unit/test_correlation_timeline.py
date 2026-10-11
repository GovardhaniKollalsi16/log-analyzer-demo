"""M6 unit tests: linking rules and the skew-aware timeline, on hand-made events."""

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
    in_kafka = kafka_ev(55, "producer", text, logger="k.Sender", client="p-1")   # 45 s skewed copy
    unrelated = kafka_ev(56, "producer", "something else", logger="k.Sender", client="p-1")
    r = correlate([in_app, in_kafka, unrelated], incident(in_app), None)
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

def skewed_pairs(skew_s: float, n=4):
    """n Kafka client lines recorded on the app clock and on a Kafka clock that runs skew_s ahead."""
    events = []
    for i in range(n):
        text = f"[Producer clientId=p-1] retrying #{i}"
        events.append(app_ev(10 * i, "svc-p", text, logger="k.Sender"))
        events.append(kafka_ev(10 * i + skew_s, "producer", text, logger="k.Sender", client="p-1"))
    return events


def test_skew_is_estimated_from_same_occurrence_and_corrected():
    events = skewed_pairs(45)
    broker = kafka_ev(40, "broker", "[Partition t-0] Shrinking ISR", partitions=[0])  # truly at app-time -5 s
    events.append(broker)
    r = correlate(events, incident(events[0]), None)
    tl = build_timeline(r.events, r.links, events[0].event_id)
    (est,) = [s for s in tl.skews if s.clock == "kafka"]
    assert (est.reference, est.offset_ms, est.basis, est.samples) == ("app:svc-p", 45000, "same_occurrence", 4)
    adjusted = {t.event_id: t.adjusted_ts for t in tl.entries}
    assert adjusted[broker.event_id] == at(-5)


def test_delivery_delay_is_not_mistaken_for_skew():
    produced = app_ev(0, "svc-p", "published", cid="c-1")
    consumed = kafka_ev(60, "message", "message t-0@1", producer="svc-p", cid="c-1", partition=0, offset=1)
    r = correlate([produced, consumed], incident(produced), None)
    tl = build_timeline(r.events, r.links, produced.event_id)
    assert all(s.basis == "none" for s in tl.skews)  # an ID link is not evidence of skew
    assert {t.event_id: t.adjusted_ts for t in tl.entries}[consumed.event_id] == at(60)


def test_reference_prefers_the_seed_clock_then_app_clocks():
    events = skewed_pairs(30)
    r = correlate(events, incident(events[0]), None)
    tl = build_timeline(r.events, r.links, seed_event_id="not-in-this-set")
    assert [s.reference for s in tl.skews if s.basis == "same_occurrence"] == ["app:svc-p"]


def test_unconnected_clocks_within_tolerance_are_order_uncertain():
    a = app_ev(0, "svc-a", "a")
    b = app_ev(30, "svc-b", "b")     # different clock, no shared occurrence, 30 s apart
    c = app_ev(200, "svc-b", "c")    # far from everything on svc-a's clock
    r = correlate([a, b, c], incident(a), None)
    tl = build_timeline(r.events, r.links, a.event_id, focus=[a.event_id, b.event_id])
    flags = {t.event_id: t.order_uncertain for t in tl.entries}
    assert flags == {a.event_id: True, b.event_id: True, c.event_id: False}
    assert {t.event_id: t.concurrent_with for t in tl.entries}[a.event_id] == [b.event_id]


def test_timeline_is_independent_of_input_order():
    events = skewed_pairs(20, n=6) + [app_ev(7, "svc-q", "q")]
    seed_id = events[0].event_id
    r1 = correlate(events, incident(events[0]), None)
    order1 = [t.event_id for t in build_timeline(r1.events, r1.links, seed_id).entries]
    shuffled = events[:]
    random.Random(3).shuffle(shuffled)
    r2 = correlate(shuffled, incident(events[0]), None)
    order2 = [t.event_id for t in build_timeline(r2.events, r2.links, seed_id).entries]
    assert order1 == order2
