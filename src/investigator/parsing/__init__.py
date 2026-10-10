"""Raw tool output -> Events (+ config entries, offsets, coverage gaps, parse issues).

Parsers never raise on bad input: a malformed line becomes a ParseIssue (kept for
tests only, Q1) and parsing continues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from investigator.adapters.base import LogSource, RawOutput
from investigator.models import ConfigEntry, CoverageGap, Event, ParseIssue

BANNER_PREFIX = "# MOCK DATA"


@dataclass
class ParseResult:
    events: List[Event] = field(default_factory=list)
    config: List[ConfigEntry] = field(default_factory=list)
    offsets: Dict[Tuple[str, int], int] = field(default_factory=dict)
    gaps: List[CoverageGap] = field(default_factory=list)
    issues: List[ParseIssue] = field(default_factory=list)

    def extend(self, other: "ParseResult") -> None:
        self.events += other.events
        self.config += other.config
        self.offsets.update(other.offsets)
        self.gaps += other.gaps
        self.issues += other.issues


def content_lines(out: RawOutput) -> Iterable[Tuple[int, str]]:
    """(1-based line number, text) for every line that isn't the banner or blank."""
    for n, line in enumerate(out.lines, start=1):
        if not line.strip() or line.startswith(BANNER_PREFIX):
            continue
        yield n, line


def parse_output(out: RawOutput) -> ParseResult:
    from investigator.parsing import dispatch
    return dispatch.parse_output(out)


def parse_all(source: LogSource) -> ParseResult:
    from investigator.dedupe import dedupe
    result = ParseResult()
    for out in source.outputs():
        result.extend(parse_output(out))
    result.events = dedupe(result.events)
    return result
