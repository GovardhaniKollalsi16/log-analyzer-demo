"""Link events and group them. Every link is labeled with its kind; no link is ever guessed from a name.

Link kinds, strongest first:
  EXACT_ID         same app + same in-app correlation_id (D25: never across apps).
                   A Kafka message's header ID belongs to its producer app.
  SAME_OCCURRENCE  one Kafka client line seen twice (in the app's own logs and in `kafka logs`):
                   identical text + logger, written within 2 s of each other. Counted once (`copies`).
  BUSINESS_KEY     same value of the seed's business key across apps/Kafka/DB, inside the incident
                   window (R22: a business key isn't request-unique, hence the window).
  THREAD_LOCAL     same cluster + app + instance + thread; a segment ends at a gap > 1 min or when
                   the thread logs a different correlation ID (D17).
  RESOURCE         two log records (app/Kafka logs, not messages) naming the same Kafka
                   topic-partition inside the window, e.g. a producer error and a broker ISR shrink.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

from investigator.config_model import attribute_clients
from investigator.models import AppTopology, CorrelationGroup, Event, Incident, Link, LinkKind, Source

THREAD_WINDOW = timedelta(minutes=1)
SAME_OCCURRENCE_WINDOW = timedelta(seconds=2)  # two copies of one line are written moments apart
WINDOW_BEFORE = timedelta(minutes=10)
WINDOW_AFTER = timedelta(minutes=2)
LINK_STRENGTH = [LinkKind.EXACT_ID, LinkKind.SAME_OCCURRENCE, LinkKind.BUSINESS_KEY, LinkKind.THREAD_LOCAL,
                 LinkKind.RESOURCE]


@dataclass
class CorrelationResult:
    events: List[Event]                                   # client IDs attributed via the seed config (D26)
    links: List[Link]
    groups: List[CorrelationGroup]
    seed_group: Optional[str]
    copies: Dict[str, str] = field(default_factory=dict)  # duplicate event_id -> canonical event_id
    resources: Dict[str, List[str]] = field(default_factory=dict)  # event_id -> ["topic-p", ...]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _chain(events: List[Event], kind: LinkKind, reason: str) -> Iterable[Link]:
    ordered = sorted(events, key=lambda e: (e.ts_utc is None, e.ts_utc, e.event_id))
    for a, b in zip(ordered, ordered[1:]):
        yield Link(a.event_id, b.event_id, kind, reason)


def _in_window(ev: Event, start: datetime, end: datetime) -> bool:
    return ev.ts_utc is not None and start <= ev.ts_utc <= end


def _searchable(ev: Event) -> str:
    err = ev.attrs.get("error") or {}
    return f"{ev.message} {err.get('message', '')}"


def resources_of(ev: Event, topics: List[str]) -> List[str]:
    """Topic-partitions a log record names. Messages and lag rows aren't log records and are excluded."""
    if ev.component in ("message", "consumer-group") or ev.source not in (Source.APP, Source.KAFKA):
        return []
    found: Set[str] = set()
    if ev.source is Source.KAFKA and ev.kafka and ev.kafka.topic:
        for p in ev.attrs.get("partitions", []):
            found.add(f"{ev.kafka.topic}-{p}")
    text = _searchable(ev)
    for topic in topics:
        for m in re.finditer(rf"\b{re.escape(topic)}-(\d+)\b", text):
            found.add(f"{topic}-{m.group(1)}")
    return sorted(found)


def correlate(events: List[Event], incident: Incident, topology: Optional[AppTopology]) -> CorrelationResult:
    events = attribute_clients(events, topology)
    by_id = {e.event_id: e for e in events}
    seed = incident.seed
    start, end = seed.ts_utc - WINDOW_BEFORE, seed.ts_utc + WINDOW_AFTER
    links: List[Link] = []

    # EXACT_ID: (app, correlation_id). A message's header ID is its producer's (app = producer).
    exact: Dict[Tuple[str, str], List[Event]] = {}
    for e in events:
        if e.app and e.ids.correlation_id:
            exact.setdefault((e.app, e.ids.correlation_id), []).append(e)
    for (app, cid), members in exact.items():
        links += _chain(members, LinkKind.EXACT_ID, f"{app} correlation_id {cid}")

    # SAME_OCCURRENCE: a Kafka client line in app logs + the same line in `kafka logs`.
    copies: Dict[str, str] = {}
    app_lines: Dict[Tuple[str, str], List[Event]] = {}
    for e in events:
        if e.source is Source.APP and e.logger:
            app_lines.setdefault((e.message, e.logger), []).append(e)
    for k in events:
        if k.source is not Source.KAFKA or k.component not in ("producer", "consumer") or k.ts_utc is None:
            continue
        candidates = [a for a in app_lines.get((k.message, k.logger or ""), [])
                      if a.ts_utc and abs(a.ts_utc - k.ts_utc) <= SAME_OCCURRENCE_WINDOW
                      and a.event_id not in copies.values()]
        if candidates:
            best = min(candidates, key=lambda a: abs(a.ts_utc - k.ts_utc))
            copies[k.event_id] = best.event_id
            links.append(Link(best.event_id, k.event_id, LinkKind.SAME_OCCURRENCE,
                              "same Kafka client line in the app's logs and in kafka logs"))

    # BUSINESS_KEY: the seed's key only, within the incident window.
    if seed.business_key:
        by_value: Dict[str, List[Event]] = {}
        for e in events:
            value = e.keys.get(seed.business_key)
            if value and _in_window(e, start, end):
                by_value.setdefault(value, []).append(e)
        for value, members in by_value.items():
            links += _chain(members, LinkKind.BUSINESS_KEY, f"{seed.business_key}={value}")

    # THREAD_LOCAL: segments per (cluster, app, instance, thread).
    threads: Dict[Tuple[Optional[str], str, str, str], List[Event]] = {}
    for e in events:
        if e.source is Source.APP and e.app and e.instance and e.thread and e.ts_utc:
            threads.setdefault((e.cluster, e.app, e.instance, e.thread), []).append(e)
    for (cluster, app, instance, thread), members in threads.items():
        members.sort(key=lambda e: (e.ts_utc, e.event_id))
        seg_cid: Optional[str] = None
        for prev, cur in zip(members, members[1:]):
            seg_cid = prev.ids.correlation_id or seg_cid
            gap = cur.ts_utc - prev.ts_utc
            switched = cur.ids.correlation_id and seg_cid and cur.ids.correlation_id != seg_cid
            if gap > THREAD_WINDOW or switched:
                seg_cid = None
                continue
            links.append(Link(prev.event_id, cur.event_id, LinkKind.THREAD_LOCAL,
                              f"{app}/{instance}/{thread} within {int(THREAD_WINDOW.total_seconds())}s"))

    # RESOURCE: same topic-partition named by log records, within the window.
    resources: Dict[str, List[str]] = {}
    by_resource: Dict[str, List[Event]] = {}
    for e in events:
        if not _in_window(e, start, end):
            continue
        res = resources_of(e, incident.kafka_topics)
        if res:
            resources[e.event_id] = res
            for r in res:
                by_resource.setdefault(r, []).append(e)
    for r, members in by_resource.items():
        links += _chain(members, LinkKind.RESOURCE, f"names {r}")

    # Groups: connected components of linked events.
    uf = _UnionFind()
    for link in links:
        uf.union(link.a, link.b)
    members_of: Dict[str, List[str]] = {}
    for eid in uf.parent:
        members_of.setdefault(uf.find(eid), []).append(eid)
    kinds_of: Dict[str, Dict[str, LinkKind]] = {}
    for link in links:
        root = uf.find(link.a)
        for eid in (link.a, link.b):
            current = kinds_of.setdefault(root, {}).get(eid)
            if current is None or LINK_STRENGTH.index(link.kind) < LINK_STRENGTH.index(current):
                kinds_of[root][eid] = link.kind
    groups: List[CorrelationGroup] = []
    roots = sorted(members_of, key=lambda r: min((by_id[e].ts_utc for e in members_of[r] if by_id[e].ts_utc),
                                                 default=seed.ts_utc))
    root_to_gid: Dict[str, str] = {}
    for i, root in enumerate(roots, start=1):
        gid = f"g-{i}"
        root_to_gid[root] = gid
        member_events = [by_id[e] for e in members_of[root]]
        ids: Dict[str, List[str]] = {}
        for e in member_events:
            if e.ids.correlation_id:
                ids.setdefault("correlation_id", []).append(f"{e.app}:{e.ids.correlation_id}")
            for k, v in e.keys.items():
                ids.setdefault(k, []).append(v)
        groups.append(CorrelationGroup(
            group_id=gid,
            ids={k: sorted(set(v)) for k, v in sorted(ids.items())},
            event_ids=sorted(members_of[root], key=lambda e: (by_id[e].ts_utc is None, by_id[e].ts_utc, e)),
            link_kinds=kinds_of.get(root, {}),
        ))
    seed_group = root_to_gid.get(uf.find(seed.event_id)) if seed.event_id in uf.parent else None
    return CorrelationResult(events=events, links=links, groups=groups, seed_group=seed_group,
                             copies=copies, resources=resources)
