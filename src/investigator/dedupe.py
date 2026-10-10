"""Collapse repeated records into one Event.

Event IDs are content hashes, so the same record fetched by two overlapping commands
gets the same ID. That's an overlap, not a duplicate: raw_refs keep every place it
was seen. `duplicate_count` counts true repeats, i.e. the most times the record
appeared within a single output.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Set

from investigator.models import Event


def dedupe(events: List[Event]) -> List[Event]:
    merged: "OrderedDict[str, Event]" = OrderedDict()
    # event_id -> command -> distinct line numbers. Re-running the same command yields the
    # same line numbers, so reruns don't inflate the count; repeats within one output do.
    lines_seen: Dict[str, Dict[str, Set[int]]] = {}
    for ev in events:
        per_cmd = lines_seen.setdefault(ev.event_id, {})
        for ref in ev.raw_refs:
            per_cmd.setdefault(ref.command, set()).add(ref.line_no)
        if ev.event_id not in merged:
            merged[ev.event_id] = ev
        else:
            first = merged[ev.event_id]
            for ref in ev.raw_refs:
                if ref not in first.raw_refs:
                    first.raw_refs.append(ref)
    for event_id, ev in merged.items():
        ev.duplicate_count = max((len(n) for n in lines_seen[event_id].values()), default=1)
    return list(merged.values())
