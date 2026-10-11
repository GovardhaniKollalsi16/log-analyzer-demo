"""Skew-aware ordering. The LLM never decides chronology; this module does, and says where it can't.

Clocks: "app:<app>", "kafka", "db". Skew between two clocks is estimated ONLY from
SAME_OCCURRENCE links (one event recorded on both clocks), so normal delivery delay
(a message consumed a minute after it was produced) is never mistaken for skew.
Within a connected set of clocks, times are adjusted to one reference clock (the seed
app's if it's in the set, else an app clock, else the busiest clock: R25). Across unconnected
clocks, events closer than the tolerance (D2: 60 s) are marked `order_uncertain`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Dict, List, Optional, Tuple

from investigator.models import DEFAULT_SKEW_TOLERANCE_MS, Event, Link, LinkKind, SkewEstimate, Source, TimelineEntry

MAX_CONCURRENT = 10


@dataclass
class TimelineResult:
    entries: List[TimelineEntry]
    skews: List[SkewEstimate]
    clock_of: Dict[str, str]            # event_id -> clock
    component_of: Dict[str, int]        # clock -> connected-clock-set id
    uncertain_count: int


def clock(ev: Event) -> Optional[str]:
    if ev.source is Source.APP:
        return f"app:{ev.app}"
    if ev.source is Source.KAFKA:
        return "kafka"
    if ev.source is Source.DB:
        return "db"
    return None  # config has no time


def build_timeline(events: List[Event], links: List[Link], seed_event_id: str,
                   tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS,
                   focus: Optional[List[str]] = None) -> TimelineResult:
    by_id = {e.event_id: e for e in events}
    timed = [e for e in events if e.ts_utc is not None and clock(e)]
    clock_of = {e.event_id: clock(e) for e in timed}

    # Pairwise offsets from SAME_OCCURRENCE: offset(b_clock relative to a_clock) = ts_b - ts_a
    samples: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for link in links:
        if link.kind is not LinkKind.SAME_OCCURRENCE or link.a not in clock_of or link.b not in clock_of:
            continue
        a, b = by_id[link.a], by_id[link.b]
        ca, cb = clock_of[a.event_id], clock_of[b.event_id]
        if ca != cb:
            ms = (b.ts_utc - a.ts_utc).total_seconds() * 1000
            samples[(ca, cb)].append(ms)
            samples[(cb, ca)].append(-ms)
    edges: Dict[str, Dict[str, float]] = defaultdict(dict)
    for (ca, cb), vals in samples.items():
        edges[ca][cb] = median(vals)

    # Connected clock sets; reference = seed clock if present, else the busiest clock.
    counts: Dict[str, int] = defaultdict(int)
    for c in clock_of.values():
        counts[c] += 1
    seed_clock = clock_of.get(seed_event_id)
    component_of: Dict[str, int] = {}
    offset_to_ref: Dict[str, float] = {}
    skews: List[SkewEstimate] = []
    for comp_id, start in enumerate(sorted(counts, key=lambda c: (c != seed_clock, -counts[c], c))):
        if start in component_of:
            continue
        members, frontier = [start], [start]
        component_of[start] = comp_id
        while frontier:
            nxt = []
            for c in frontier:
                for d in edges.get(c, {}):
                    if d not in component_of:
                        component_of[d] = comp_id
                        members.append(d)
                        nxt.append(d)
            frontier = nxt
        # Only relative offsets are measurable; which clock is "right" is an assumption (R25):
        # the seed's clock if it's in this set, else an app clock (the services under
        # investigation), else the busiest clock.
        apps = [c for c in members if c.startswith("app:")]
        ref = seed_clock if seed_clock in members else max(apps or members, key=lambda c: (counts[c], c))
        offset_to_ref[ref] = 0.0
        frontier = [ref]
        while frontier:  # BFS accumulating offsets from the reference
            nxt = []
            for c in frontier:
                for d, ms in edges.get(c, {}).items():
                    if d not in offset_to_ref:
                        offset_to_ref[d] = offset_to_ref[c] + ms
                        nxt.append(d)
            frontier = nxt
        for c in sorted(members):
            if c != ref:
                n = sum(len(v) for (x, _), v in samples.items() if x == c)  # same-occurrence pairs on this clock
                skews.append(SkewEstimate(clock=c, reference=ref, offset_ms=int(round(offset_to_ref[c])),
                                          basis="same_occurrence", samples=n))
            elif len(members) == 1:
                skews.append(SkewEstimate(clock=c, reference=c, offset_ms=0, basis="none"))

    adjusted = {e.event_id: e.ts_utc - timedelta(milliseconds=offset_to_ref.get(clock_of[e.event_id], 0.0))
                for e in timed}
    order = sorted(timed, key=lambda e: (adjusted[e.event_id], clock_of[e.event_id], e.event_id))

    # Uncertainty: events from a different, unconnected clock set within the tolerance.
    tol = timedelta(milliseconds=tolerance_ms)
    focus_set = set(focus or [])
    by_comp: Dict[int, List[Event]] = defaultdict(list)
    for e in order:
        by_comp[component_of[clock_of[e.event_id]]].append(e)
    entries: List[TimelineEntry] = []
    uncertain = 0
    for e in order:
        my_comp = component_of[clock_of[e.event_id]]
        t = adjusted[e.event_id]
        close = [o for comp, evs in by_comp.items() if comp != my_comp for o in evs
                 if abs(adjusted[o.event_id] - t) < tol]
        is_uncertain = bool(close)
        uncertain += is_uncertain
        concurrent = [o.event_id for o in close if o.event_id in focus_set][:MAX_CONCURRENT] \
            if e.event_id in focus_set else []
        entries.append(TimelineEntry(
            event_id=e.event_id, adjusted_ts=t,
            skew_applied_ms=-int(round(offset_to_ref.get(clock_of[e.event_id], 0.0))),
            order_uncertain=is_uncertain, concurrent_with=concurrent,
        ))
    return TimelineResult(entries=entries, skews=skews, clock_of=clock_of, component_of=component_of,
                          uncertain_count=uncertain)
