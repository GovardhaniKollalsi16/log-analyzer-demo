"""The synthetic world a scenario generates, before any rendering.

Every record carries `critical`: True for lines the scenario's evidence depends on.
Perturbation knobs (drop, malform) only ever touch non-critical records, so
robustness tests can perturb freely without deleting the story.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class AppLogLine:
    ts: datetime
    level: str
    app: str
    instance: str
    thread: str
    logger: str
    msg: str
    correlation_id: Optional[str] = None
    error: Optional[Dict[str, str]] = None
    critical: bool = False


@dataclass
class KafkaMessage:
    topic: str
    partition: int
    offset: int
    ts: datetime
    headers: Dict[str, str]
    value: Dict[str, Any]


@dataclass
class KafkaLogLine:
    ts: datetime
    level: str
    component: str  # broker | producer | consumer
    topic: str
    text: str
    logger: str
    critical: bool = False


@dataclass
class DbLogLine:
    ts: datetime
    pid: int
    app: str
    user: str
    db: str
    severity: str  # LOG | WARNING | ERROR | FATAL | PANIC
    msg: str
    critical: bool = False


@dataclass
class GroupInfo:
    group: str
    topic: str
    client_id: str  # = consuming app
    consumer_id: str
    host: str


@dataclass
class Deployment:
    app: str
    cluster: str
    namespace: str
    instances: List[str]


@dataclass
class Incident:
    seed_record: AppLogLine  # rendered exactly as the app logs it (render.incident_text)
    app: Optional[Tuple[str, str]]  # (cluster, namespace) of the seed app; None = omitted
    related_apps: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    kafka_bootstrap: Optional[str] = None
    kafka_topics: List[str] = field(default_factory=list)
    kafka_group: Optional[str] = None
    db_host: Optional[str] = None
    db_name: Optional[str] = None


@dataclass
class World:
    now: datetime  # "current time" from the tools' point of view (lag snapshots, offsets)
    deployments: Dict[str, Deployment]
    configs: Dict[str, Dict[str, str]]  # app -> configmap data
    bootstrap: str
    topics: Dict[str, int]  # topic -> partition count
    base_offsets: Dict[Tuple[str, int], int]  # (topic, partition) -> first offset in the window
    messages: List[KafkaMessage]
    groups: List[GroupInfo]
    app_logs: List[AppLogLine]
    kafka_logs: List[KafkaLogLine]
    db_host: str
    db_name: str
    db_logs: List[DbLogLine]
    incident: Incident
    # Access denials = the user's missing entitlements (D16), e.g. "config:<app>",
    # "logs:<app>", "kafka-topic:<topic>", "kafka-group:<group>", "db:<db>".
    denied: Set[str] = field(default_factory=set)
    # Per-source clock skew in ms: keys "app:<app>", "kafka", "db".
    skew_ms: Dict[str, int] = field(default_factory=dict)
