"""Detectors (M7_RULES §1): cross-record patterns over classified, linked events.

Every Finding cites concrete event IDs. Detectors match codes, structure and resources,
never app/topic/scenario names. Same-occurrence copies are ignored, so nothing is counted twice.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from investigator.adapters.base import RawOutput
from investigator.correlation import WINDOW_AFTER, WINDOW_BEFORE, CorrelationResult
from investigator.models import AppTopology, Event, Finding, Incident, Severity, Source

MIN_RETRIES = 2          # D-1
MIN_POISON_FAILURES = 3  # D-4
MIN_DB_ERRORS = 3        # D-5

RETRY_CODES = {"app.retry_attempt", "kafka.producer.retry"}
GIVE_UP_CODES = {"app.retries_exhausted", "kafka.producer.record_expired", "kafka.producer.delivery_failed"}
KEY_FAILURE_CODES = {"app.publish_failed", "app.event_wait_timeout", "app.retries_exhausted"}
POISON_CODES = {"kafka.consumer.processing_failed", "kafka.consumer.deserialization_failed",
                "kafka.consumer.dead_lettered"}
CONFIG_EXPLAINS = {  # config anomaly key -> observed codes it explains
    "db.pool.size": {"db.too_many_connections", "app.pool_saturated", "app.db_call_failed"},
    "worker.threads": {"db.too_many_connections", "app.pool_saturated", "app.db_call_failed"},
}
TIMEOUT_CODES = {"app.event_wait_timeout", "app.outbound_timeout", "db.statement_timeout", "app.db_call_failed"}
_CLIENT = re.compile(r"clientId=([^,\]\s]+)")
_OFFSET = re.compile(r"\boffset (\d+)", re.I)


@dataclass
class Context:
    incident: Incident
    cor: CorrelationResult
    topology: Optional[AppTopology]
    outputs: List[RawOutput]
    events: List[Event] = field(init=False)
    by_id: Dict[str, Event] = field(init=False)
    seed_group: Set[str] = field(init=False)

    def __post_init__(self) -> None:
        # copies (the kafka-logs twin of an app-log line) are dropped: count each occurrence once
        self.events = [e for e in self.cor.events if e.event_id not in self.cor.copies]
        self.by_id = {e.event_id: e for e in self.cor.events}
        group = next((g for g in self.cor.groups if g.group_id == self.cor.seed_group), None)
        self.seed_group = set(group.event_ids) if group else {self.incident.seed.event_id}

    def in_window(self, e: Event) -> bool:
        s = self.incident.seed.ts_utc
        return e.ts_utc is not None and s - WINDOW_BEFORE <= e.ts_utc <= s + WINDOW_AFTER


def _finding(detector: str, n: int, events: List[Event], summary: str, **attrs) -> Finding:
    ordered = sorted(events, key=lambda e: (e.ts_utc is None, e.ts_utc, e.event_id))
    return Finding(finding_id=f"f-{detector}-{n}", detector=detector, kind=detector,
                   event_ids=[e.event_id for e in ordered], summary=summary, attrs=dict(attrs))


# --- D-1 retry_exhaustion ---------------------------------------------------------------

def retry_exhaustion(ctx: Context) -> List[Finding]:
    by_key: Dict[str, List[Event]] = defaultdict(list)
    for e in ctx.events:
        if e.error_code in RETRY_CODES | GIVE_UP_CODES and e.ts_utc and ctx.in_window(e):
            client = e.attrs.get("client_id") or (_CLIENT.search(e.message).group(1) if _CLIENT.search(e.message) else None)
            res = ctx.cor.resources.get(e.event_id, [])
            key = f"client:{client}" if client else (f"resource:{res[0]}" if res else None)
            if key:
                by_key[key].append(e)
    out, n = [], 0
    for key, evs in sorted(by_key.items()):
        retries: List[Event] = []
        for e in sorted(evs, key=lambda e: (e.ts_utc, e.event_id)):
            if e.error_code in RETRY_CODES:
                retries.append(e)
            elif retries and len(retries) >= MIN_RETRIES:
                n += 1
                out.append(_finding("retry_exhaustion", n, retries + [e],
                                    f"{len(retries)} retries then {e.error_code} ({key})", key=key, retries=len(retries)))
                retries = []
            else:
                retries = []
    return out


# --- D-2 delivery_failure_chain -------------------------------------------------------------

def delivery_failure_chain(ctx: Context) -> List[Finding]:
    by_res: Dict[str, List[Event]] = defaultdict(list)
    for eid, res in ctx.cor.resources.items():
        e = ctx.by_id[eid]
        if eid in ctx.cor.copies or e.severity is Severity.CONTEXT:
            continue
        for r in res:
            by_res[r].append(e)
    out, n = [], 0
    for r, evs in sorted(by_res.items()):
        broker = [e for e in evs if e.component == "broker"]
        client_or_app = [e for e in evs if e.component != "broker" and e.severity is Severity.ERROR]
        linked = any(e.event_id in ctx.seed_group for e in evs)
        if broker and client_or_app and linked:
            n += 1
            out.append(_finding("delivery_failure_chain", n, broker + client_or_app,
                                f"broker trouble and delivery errors on {r}", resource=r))
    return out


# --- D-3 missing_message --------------------------------------------------------------------

def missing_message(ctx: Context) -> List[Finding]:
    seed = ctx.incident.seed
    if not seed.business_key:
        return []
    value = seed.keys.get(seed.business_key)
    searched: Dict[str, Dict[str, int]] = defaultdict(dict)  # topic -> {argv: message count}
    for out in ctx.outputs:
        a = out.argv
        if len(a) > 1 and a[1] == "kafka-console-consumer" and "--grep" in a and a[a.index("--grep") + 1] == value \
                and out.exit_code == 0:
            topic = a[a.index("--topic") + 1]
            count = sum(1 for l in out.lines if l.strip() and not l.startswith("#") and not l.startswith("Processed"))
            searched[topic][" ".join(a[:a.index("--save-dir")] if "--save-dir" in a else a)] = count
    empty_topics = sorted(t for t, runs in searched.items() if runs and all(c == 0 for c in runs.values()))
    failures = [e for e in ctx.events if e.keys.get(seed.business_key) == value and e.error_code in KEY_FAILURE_CODES]
    if not empty_topics or not failures:
        return []
    absence = [{"topic": t, "searches": sorted(searched[t])} for t in empty_topics]
    return [_finding("missing_message", 1, failures,
                     f"no message with {seed.business_key}={value} on {', '.join(empty_topics)}",
                     business_key=seed.business_key, value=value, absence=absence)]


# --- D-4 poison_message ----------------------------------------------------------------------

def poison_message(ctx: Context) -> List[Finding]:
    by_offset: Dict[str, List[Event]] = defaultdict(list)
    for e in ctx.events:
        if e.error_code in POISON_CODES and ctx.in_window(e):
            topic = e.kafka.topic if e.kafka else None
            partition = e.kafka.partition if e.kafka else None
            m = _OFFSET.search(e.message)
            offset = (e.kafka.offset if e.kafka and e.kafka.offset is not None else (int(m.group(1)) if m else None))
            if topic is not None and offset is not None:
                by_offset[f"{topic}-{partition}@{offset}"].append(e)
    out, n = [], 0
    for key, evs in sorted(by_offset.items()):
        if len(evs) >= MIN_POISON_FAILURES:
            n += 1
            out.append(_finding("poison_message", n, evs, f"{len(evs)} processing failures on {key}", at=key))
    return out


# --- D-5 db_error_burst ---------------------------------------------------------------------

def db_error_burst(ctx: Context) -> List[Finding]:
    by_app: Dict[str, List[Event]] = defaultdict(list)
    for e in ctx.events:
        if e.source is Source.DB and e.severity is Severity.ERROR and ctx.in_window(e):
            by_app[f"{e.app or '?'}@{e.attrs.get('db', '?')}"].append(e)
    out, n = [], 0
    for key, evs in sorted(by_app.items()):
        if len(evs) >= MIN_DB_ERRORS:
            n += 1
            out.append(_finding("db_error_burst", n, evs, f"{len(evs)} DB errors from {key}", at=key))
    return out


# --- D-6 config_vs_observed -----------------------------------------------------------------

def config_vs_observed(ctx: Context) -> List[Finding]:
    seed_app = ctx.incident.seed.app
    config = [e for e in ctx.cor.events if e.source is Source.APP_CONFIG and e.app == seed_app]
    observed = [e for e in ctx.events if e.severity is Severity.ERROR and ctx.in_window(e)
                and (e.app == seed_app or e.source is Source.DB)]
    out, n = [], 0
    for c in config:
        key, value = c.attrs.get("key", ""), c.attrs.get("value", "")
        if c.severity is Severity.ANOMALY and key in CONFIG_EXPLAINS:
            hits = [e for e in observed if e.error_code in CONFIG_EXPLAINS[key]]
            if hits:
                n += 1
                out.append(_finding("config_vs_observed", n, [c] + hits,
                                    f"config {key}={value} ({c.error_code}) and matching errors", key=key))
        elif key.endswith(".timeout.ms") and value.isdigit():
            hits = [e for e in observed if e.error_code in TIMEOUT_CODES
                    and re.search(rf"\b{value}\s?ms\b", f"{e.message} {(e.attrs.get('error') or {}).get('message', '')}")]
            if hits:
                n += 1
                out.append(_finding("config_vs_observed", n, [c] + hits,
                                    f"configured {key}={value} matches the observed timeout", key=key))
    return out


# --- D-7 first_error_per_app ------------------------------------------------------------------

def first_error_per_app(ctx: Context) -> List[Finding]:
    first: Dict[str, Event] = {}
    for e in sorted((ctx.by_id[i] for i in ctx.seed_group if i in ctx.by_id), key=lambda e: (e.ts_utc is None, e.ts_utc)):
        if e.app and e.severity is Severity.ERROR and e.event_id not in ctx.cor.copies:
            first.setdefault(e.app, e)
    return [_finding("first_error_per_app", i, [e], f"first ERROR of {app}", app=app)
            for i, (app, e) in enumerate(sorted(first.items()), start=1)]


DETECTORS = [retry_exhaustion, delivery_failure_chain, missing_message, poison_message, db_error_burst,
             config_vs_observed, first_error_per_app]
INFORMATIONAL = {"first_error_per_app"}  # reported, but never used to build hypotheses


def run_all(ctx: Context) -> List[Finding]:
    return [f for detector in DETECTORS for f in detector(ctx)]


