"""App config (PROPOSAL §2.2): ANOMALY only, judged within ONE app's config.

In M4: invalid values and internal inconsistencies. Checks that need other sources
(a timeout vs. observed latencies, a topic missing from Kafka, a DB never seen) are
cross-source by nature and belong to the detectors (M7). No change history (D20).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

from investigator.models import Event, Severity

NUMERIC_SUFFIXES = (".ms", ".timeout", ".size", ".threads", ".retries", ".count")


def _int(v: Optional[str]) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _invalid(cfg: Dict[str, str]) -> List[Tuple[List[str], str]]:
    out = []
    for key, value in cfg.items():
        if key.endswith(NUMERIC_SUFFIXES):
            n = _int(value)
            if n is None or n < 0:
                out.append(([key], f"{key}={value!r} is not a non-negative integer"))
    return out


def _pool_below_workers(cfg: Dict[str, str]) -> List[Tuple[List[str], str]]:
    pool, workers = _int(cfg.get("db.pool.size")), _int(cfg.get("worker.threads"))
    if pool is not None and workers is not None and pool < workers:
        return [(["db.pool.size", "worker.threads"], f"DB pool size {pool} < worker threads {workers}")]
    return []


def _retries_exceed_poll(cfg: Dict[str, str]) -> List[Tuple[List[str], str]]:
    retries = _int(cfg.get("kafka.producer.retries"))
    req = _int(cfg.get("kafka.producer.request.timeout.ms"))
    poll = _int(cfg.get("kafka.consumer.max.poll.interval.ms"))
    if None not in (retries, req, poll) and (retries + 1) * req > poll:  # type: ignore[operator]
        return [(["kafka.producer.retries", "kafka.producer.request.timeout.ms", "kafka.consumer.max.poll.interval.ms"],
                 f"(retries+1) x request timeout = {(retries + 1) * req} ms > max poll interval {poll} ms")]  # type: ignore[operator]
    return []


CHECKS: List[Tuple[str, str, Callable[[Dict[str, str]], List[Tuple[List[str], str]]]]] = [
    ("config.invalid_value", "A timeout/size/count key that isn't a non-negative integer", _invalid),
    ("config.inconsistent", "DB pool size smaller than the app's worker threads", _pool_below_workers),
    ("config.inconsistent", "(retries + 1) x request timeout longer than the consumer's max poll interval",
     _retries_exceed_poll),
]


def classify_config(events: List[Event]) -> List[Event]:
    by_app: Dict[Optional[str], Dict[str, Event]] = {}
    for ev in events:
        by_app.setdefault(ev.app, {})[ev.attrs["key"]] = ev
    flagged: Dict[str, Tuple[str, str]] = {}
    for app_events in by_app.values():
        cfg = {k: e.attrs["value"] for k, e in app_events.items()}
        for code, _, check in CHECKS:
            for keys, reason in check(cfg):
                for key in keys:
                    flagged.setdefault(app_events[key].event_id, (code, reason))
    out = []
    for ev in events:
        if ev.event_id in flagged:
            code, reason = flagged[ev.event_id]
            ev = replace(ev, severity=Severity.ANOMALY, error_code=code, attrs={**ev.attrs, "anomaly": reason})
        out.append(ev)
    return out
