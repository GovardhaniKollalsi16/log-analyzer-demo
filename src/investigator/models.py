"""Core data models shared by every stage of the deterministic pipeline (design Rev 2).

Flow: seed line -> Seed; fetched raw output -> RawRecord -> (parse) -> Event
-> (classify) Event with Severity/error_code -> CorrelationGroup -> TimelineEntry
-> Finding -> Hypothesis -> AnalysisBundle (handed to the LLM).
Traversal: Seed + AppTopology -> FetchPlan of FetchSteps; anything unreachable -> CoverageGap.

Report models live in `investigator.report` (M9), not here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

DEFAULT_SKEW_TOLERANCE_MS = 60_000      # D2: Kafka events have been seen about 1 min late; tune later.
THREAD_SEGMENT_WINDOW_MS = 60_000       # D17: thread links within 1 min, stop early at a new correlation ID.


class Source(str, enum.Enum):
    """The four components the traversal reads (Rev 2)."""

    APP = "app"
    APP_CONFIG = "app_config"
    KAFKA = "kafka"
    DB = "db"


class Level(str, enum.Enum):
    """The level the log record itself declared. Not the same as Severity."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _LEVEL_ORDER.index(self)


_LEVEL_ORDER = [Level.DEBUG, Level.INFO, Level.WARN, Level.ERROR, Level.CRITICAL]


class Severity(str, enum.Enum):
    """Per-component classification (PROPOSAL §2), decided by investigator.classify."""

    ERROR = "ERROR"      # the component failed to do its job
    SYMPTOM = "SYMPTOM"  # degraded, not failed
    CONTEXT = "CONTEXT"  # normal activity, useful for chronology
    ANOMALY = "ANOMALY"  # app config only


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


class FactorName(str, enum.Enum):
    ID_LINKAGE = "id_linkage"
    TRAVERSAL_COVERAGE = "traversal_coverage"
    TEMPORAL_PRECEDENCE = "temporal_precedence"
    COMPETING_HYPOTHESES = "competing_hypotheses"


class FactorValue(str, enum.Enum):
    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    WEAK = "WEAK"
    ABSENT = "ABSENT"


class LinkKind(str, enum.Enum):
    EXACT_ID = "exact_id"            # same app + same in-app correlation ID (D25: correlation IDs are per app)
    BUSINESS_KEY = "business_key"    # same business key (order_id, product_id, ...) across apps; not request-unique (R22)
    THREAD_LOCAL = "thread_local"    # same cluster + app + instance + thread segment (D17); weaker than an ID
    WEAK_TEMPORAL = "weak_temporal"  # no ID, no thread; time + app only. Last resort, always labeled


class ParseIssueKind(str, enum.Enum):
    MALFORMED = "malformed"
    BAD_TIMESTAMP = "bad_timestamp"
    UNKNOWN_FORMAT = "unknown_format"
    MISSING_FIELD = "missing_field"


class Direction(str, enum.Enum):
    SEED = "seed"
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"


class GapReason(str, enum.Enum):
    ACCESS_DENIED = "access_denied"  # user's entitlements don't cover it (D16)
    AUTH_REQUIRED = "auth_required"  # SSO session missing/expired and the user did not re-authenticate (D21)
    MISSING_INPUT = "missing_input"  # a required input wasn't in the incident; the step was not run (D22)
    NOT_FOUND = "not_found"
    EMPTY = "empty"


@dataclass(frozen=True)
class RawRecord:
    """Provenance for one raw line: where it came from and exactly what it said."""

    source: Source
    command: str
    line_no: int
    text: str


@dataclass(frozen=True)
class ParseIssue:
    """Returned by parsers so tests can assert malformed input was handled.

    Not part of the AnalysisBundle and not a confidence factor (Q1).
    """

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


@dataclass(frozen=True)
class KafkaRef:
    topic: str
    partition: Optional[int] = None
    offset: Optional[int] = None
    group: Optional[str] = None
    client_id: Optional[str] = None
    producer_app: Optional[str] = None  # from message headers; how upstream apps are found (R13)


@dataclass
class Event:
    """One normalized, deduplicated record. `event_id` is what reports cite.

    `app` is the application the record belongs to: the emitting app for app logs,
    the client/producing app for Kafka records when known, and the connecting app
    for DB records when known. `component` is the sub-part (producer, broker,
    consumer, db-server, ...).
    """

    event_id: str
    source: Source
    level: Level
    message: str
    ts_raw: str
    ts_utc: Optional[datetime]  # None when the timestamp was unparseable
    app: Optional[str] = None
    component: Optional[str] = None
    cluster: Optional[str] = None
    namespace: Optional[str] = None
    instance: Optional[str] = None
    thread: Optional[str] = None
    logger: Optional[str] = None
    severity: Severity = Severity.CONTEXT
    error_code: Optional[str] = None
    ids: Ids = field(default_factory=Ids)  # in-app IDs; correlation_id belongs to `app` only (D25)
    keys: Dict[str, str] = field(default_factory=dict)  # business keys, e.g. {"order_id": "o-1"} (D25)
    kafka: Optional[KafkaRef] = None
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
        # Classification invariants (PROPOSAL §2): every non-CONTEXT record carries a code.
        if (self.severity is Severity.CONTEXT) != (self.error_code is None):
            raise ValueError(
                f"error_code must be set exactly when severity is not CONTEXT "
                f"(severity={self.severity.value}, error_code={self.error_code!r})"
            )
        if self.severity is Severity.ANOMALY and self.source is not Source.APP_CONFIG:
            raise ValueError("ANOMALY severity is only valid for app config records")
        if self.thread is not None and (self.app is None or self.instance is None):
            raise ValueError("thread is only meaningful with app and instance (threads are not global IDs)")


@dataclass(frozen=True)
class Seed:
    """The app error line the investigation starts from (the incident's `seed:` line, D19/D23)."""

    event_id: str
    app: str
    ts_utc: datetime
    cluster: Optional[str] = None
    namespace: Optional[str] = None
    instance: Optional[str] = None
    thread: Optional[str] = None
    logger: Optional[str] = None
    correlation_id: Optional[str] = None
    keys: Dict[str, str] = field(default_factory=dict)
    business_key: Optional[str] = None  # key NAME chosen by the correlation-key table; value is keys[name]
    error_code: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.app:
            raise ValueError("seed must name the application")
        if self.ts_utc.utcoffset() != timedelta(0):
            raise ValueError(f"seed ts_utc must be timezone-aware UTC, got {self.ts_utc!r}")


@dataclass(frozen=True)
class Location:
    cluster: str
    namespace: str


@dataclass
class Incident:
    """The agent's first message (D23). Absent lines stay None/empty: no input, no access (D22)."""

    seed: Seed
    seed_event: "Event"
    app: Optional[Location] = None                                      # seed app only
    related_apps: Dict[str, Location] = field(default_factory=dict)     # app[<name>]: lines
    kafka_bootstrap: Optional[str] = None
    kafka_topics: List[str] = field(default_factory=list)
    kafka_group: Optional[str] = None
    db_host: Optional[str] = None
    db_name: Optional[str] = None


@dataclass(frozen=True)
class ConfigEntry:
    """One key from an app's config. No change history is used (D20)."""

    app: str
    key: str
    value: str
    raw_ref: RawRecord


@dataclass(frozen=True)
class TopicSubscription:
    topic: str
    group: str


@dataclass
class AppTopology:
    """What the seed app's config says it is connected to."""

    app: str
    consumes: List[TopicSubscription] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    databases: List[str] = field(default_factory=list)
    limits: Dict[str, str] = field(default_factory=dict)  # timeouts, retries, pool sizes, ...


@dataclass
class FetchStep:
    """One allowlisted command the planner wants run next, and why."""

    order: int
    component: Source
    target: str
    argv: List[str]
    reason: str
    direction: Direction = Direction.SEED

    def __post_init__(self) -> None:
        if not self.argv:
            raise ValueError("argv must be non-empty")


@dataclass
class FetchPlan:
    steps: List[FetchStep] = field(default_factory=list)
    done: bool = False
    stop_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.done and not self.stop_reason:
            raise ValueError("a finished plan must say why it stopped")


@dataclass(frozen=True)
class CoverageGap:
    component: Source
    target: str
    reason: GapReason
    detail: str = ""


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
    name: FactorName
    value: FactorValue
    reason: str


@dataclass
class AnalysisBundle:
    """Everything the LLM is allowed to reason over. It never sees raw logs directly."""

    bundle_id: str
    seed: Optional[Seed] = None
    topology: Optional[AppTopology] = None
    skew_tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS
    traversal: List[FetchStep] = field(default_factory=list)
    coverage_gaps: List[CoverageGap] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    groups: List[CorrelationGroup] = field(default_factory=list)
    timeline: List[TimelineEntry] = field(default_factory=list)
    skew_estimates: List[SkewEstimate] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    hypotheses: List[Hypothesis] = field(default_factory=list)
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
