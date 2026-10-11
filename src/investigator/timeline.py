"""Chronological ordering. The LLM never decides chronology; this module does.

Events are ordered by their own UTC timestamps. Clock drift between machines is not a
concern for this tool (D30: the incident window is wide), so nothing is measured or
adjusted. Ties are broken deterministically, so input order never changes the result.
Events without a timestamp (config entries) aren't on the timeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from investigator.models import Event, TimelineEntry

_SOURCE_ORDER = {"app": 0, "kafka": 1, "db": 2}


@dataclass
class TimelineResult:
    entries: List[TimelineEntry]


def build_timeline(events: List[Event], only: Optional[Iterable[str]] = None) -> TimelineResult:
    """Order events by UTC timestamp. `only` restricts the timeline to those event IDs."""
    keep = set(only) if only is not None else None
    timed = [e for e in events if e.ts_utc is not None and (keep is None or e.event_id in keep)]
    timed.sort(key=lambda e: (e.ts_utc, _SOURCE_ORDER.get(e.source.value, 9), e.event_id))
    return TimelineResult(entries=[TimelineEntry(event_id=e.event_id, ts_utc=e.ts_utc) for e in timed])
