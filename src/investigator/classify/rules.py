"""Shared rule machinery for per-component classification (PROPOSAL §2).

A rule table is an ordered list of Rule; the first matching rule wins, and no match
means CONTEXT. Rules match on structure and wording patterns, never on app, topic,
cluster or scenario names (the boundary test enforces the names part).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from investigator.models import Event, Level, Severity


@dataclass(frozen=True)
class Thresholds:
    """All tunable numbers in one place (to be tuned from real data)."""

    slow_call_fraction: float = 0.8   # app: a call slower than 0.8 x its configured timeout
    slow_query_ms: float = 500.0      # db: statement duration above this
    lag_threshold: int = 100          # kafka: a lag above this counts
    lag_growth_samples: int = 2       # kafka: lag must rise across at least this many consecutive samples


@dataclass(frozen=True)
class Rule:
    error_code: str
    severity: Severity
    description: str                              # human-readable, shown in reviews and reports
    levels: Tuple[Level, ...] = ()                # empty = any level
    pattern: Optional["re.Pattern[str]"] = None   # searched in message + error type/message
    components: Tuple[str, ...] = ()              # empty = any component
    when: Optional[Callable[[Event], bool]] = None

    def matches(self, ev: Event) -> bool:
        if self.levels and ev.level not in self.levels:
            return False
        if self.components and (ev.component or "") not in self.components:
            return False
        if self.pattern is not None and not self.pattern.search(searchable(ev)):
            return False
        if self.when is not None and not self.when(ev):
            return False
        return True


def searchable(ev: Event) -> str:
    err = ev.attrs.get("error") or {}
    return " ".join([ev.message, str(err.get("type", "")), str(err.get("message", ""))])


def rx(pattern: str) -> "re.Pattern[str]":
    return re.compile(pattern, re.IGNORECASE)


ERROR_LEVELS = (Level.ERROR, Level.CRITICAL)


def first_match(rules: Sequence[Rule], ev: Event) -> Optional[Rule]:
    return next((r for r in rules if r.matches(ev)), None)
