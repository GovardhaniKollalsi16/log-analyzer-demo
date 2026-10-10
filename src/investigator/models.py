"""Core data models shared by every stage of the deterministic pipeline.

Flow: RawRecord -> (parse) -> Event | ParseIssue -> CorrelationGroup -> TimelineEntry
-> Finding -> Hypothesis -> AnalysisBundle (handed to the LLM).

Report models live in `investigator.report` (M7), not here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

DEFAULT_SKEW_TOLERANCE_MS = 60_000  # D2: Kafka events have been seen about 1 min late; tune later.


class Source(str, enum.Enum):
    APP = "app"
    UPSTREAM = "upstream"
    KAFKA = "kafka"
    DB = "db"


class Level(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _LEVEL_ORDER.index(self)

    @property
    def is_error(self) -> bool:
        return self.rank >= Level.ERROR.rank


_LEVEL_ORDER = [Level.DEBUG, Level.INFO, Level.WARN, Level.ERROR, Level.CRITICAL]


class Confidence(str, enum.Enum):
    """Categorical confidence. Never a float."""

    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        return _CONFIDENCE_ORDER.index(self)

    def at_most(self, cap: Confidence) -> bool:
        return self.rank <= cap.rank


_CONFIDENCE_ORDER = [Confidence.INSUFFICIENT, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]


class FactorValue(str, enum.Enum):
    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    WEAK = "WEAK"
    ABSENT = "ABSENT"


class LinkKind(str, enum.Enum):
    EXACT_ID = "exact_id"            # shares a correlation/trace/message/request ID
    WEAK_TEMPORAL = "weak_temporal"  # no shared ID; attached by time + service only, always labeled


class ParseIssueKind(str, enum.Enum):
    MALFORMED = "malformed"
    BAD_TIMESTAMP = "bad_timestamp"
    UNKNOWN_FORMAT = "unknown_format"
    MISSING_FIELD = "missing_field"


@dataclass(frozen=True)
class RawRecord:
    """Provenance for one raw line: where it came from and exactly what it said."""

    source: Source
    command: str
    line_no: int
    text: str


@dataclass(frozen=True)
class ParseIssue:
    source: Source
    line_no: int
    kind: ParseIssueKind
    text: str
    detail: str = ""


@dataclass(frozen=True)
class Ids:
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    message_id: Optional[str] = None
    request_id: Optional[str] = None

    def present(self) -> Dict[str, str]:
        """Only the IDs that are set, as {kind: value}."""
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name)}

    def is_empty(self) -> bool:
        return not self.present()


@dataclass
class Event:
    """One normalized, deduplicated log event. `event_id` is what reports cite."""

    event_id: str
    source: Source
    service: str
    level: Level
    message: str
    ts_raw: str
    ts_utc: Optional[datetime]  # None when the timestamp was unparseable (a ParseIssue is also recorded)
    component: Optional[str] = None
    ids: Ids = field(default_factory=Ids)
    attrs: Dict[str, Any] = field(default_factory=dict)
    raw_refs: List[RawRecord] = field(default_factory=list)
    duplicate_count: int = 1

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must be non-empty")
        if self.ts_utc is not None and self.ts_utc.utcoffset() != timedelta(0):
            raise ValueError(f"ts_utc must be timezone-aware UTC, got {self.ts_utc!r}")
        if self.duplicate_count < 1:
            raise ValueError("duplicate_count must be >= 1")


@dataclass
class CorrelationGroup:
    group_id: str
    ids: Dict[str, List[str]]  # {"correlation_id": [...], "message_id": [...], ...}
    event_ids: List[str]
    link_kinds: Dict[str, LinkKind] = field(default_factory=dict)  # event_id -> how it joined


@dataclass
class SkewEstimate:
    source: Source
    offset_ms: int
    basis: str  # "causal_pairs" | "none"
    samples: int = 0


@dataclass
class TimelineEntry:
    event_id: str
    adjusted_ts: Optional[datetime]
    skew_applied_ms: int = 0
    order_uncertain: bool = False
    concurrent_with: List[str] = field(default_factory=list)


@dataclass
class Finding:
    """Output of one rule-based detector. Always backed by concrete event IDs."""

    finding_id: str
    detector: str
    kind: str
    event_ids: List[str]
    summary: str
    attrs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_ids:
            raise ValueError(f"finding {self.finding_id!r} must cite at least one event_id")


@dataclass
class Hypothesis:
    """A candidate cause -> effect chain. Unranked: the LLM chooses, the code only checks."""

    hyp_id: str
    cause_finding_ids: List[str]
    effect_finding_ids: List[str]
    precedence_ok: bool
    id_linked: bool


@dataclass
class ConfidenceFactor:
    name: str  # id_linkage | source_coverage | temporal_precedence | competing_hypotheses | data_quality
    value: FactorValue
    reason: str


@dataclass
class AnalysisBundle:
    """Everything the LLM is allowed to reason over. It never sees raw logs directly."""

    bundle_id: str
    skew_tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS
    sources_queried: List[Source] = field(default_factory=list)
    coverage_gaps: List[str] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    groups: List[CorrelationGroup] = field(default_factory=list)
    timeline: List[TimelineEntry] = field(default_factory=list)
    skew_estimates: List[SkewEstimate] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    hypotheses: List[Hypothesis] = field(default_factory=list)
    parse_issues: List[ParseIssue] = field(default_factory=list)
    factors: List[ConfidenceFactor] = field(default_factory=list)
    confidence_cap: Confidence = Confidence.INSUFFICIENT

    def event_ids(self) -> Set[str]:
        return {e.event_id for e in self.events}


def to_jsonable(obj: Any) -> Any:
    """Convert models to JSON-safe structures. Datetimes become ISO-8601 with a 'Z' suffix."""
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise ValueError(f"refusing to serialize naive datetime {obj!r}")
        return obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {str(to_jsonable(k)): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(to_jsonable(v) for v in obj)
    return obj
