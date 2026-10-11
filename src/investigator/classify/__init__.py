"""Per-component classification: every Event gets a Severity and (if not CONTEXT) an error_code."""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional

from investigator.classify import app as app_rules
from investigator.classify import db as db_rules
from investigator.classify import kafka as kafka_rules
from investigator.classify.config import classify_config
from investigator.classify.rules import Thresholds, first_match
from investigator.models import Event, Severity, Source

__all__ = ["classify", "Thresholds"]


def _by_rules(ev: Event, rules) -> Event:
    rule = first_match(rules, ev)
    if rule is None:
        return replace(ev, severity=Severity.CONTEXT, error_code=None)
    return replace(ev, severity=rule.severity, error_code=rule.error_code)


def classify(events: List[Event], thresholds: Optional[Thresholds] = None) -> List[Event]:
    t = thresholds or Thresholds()
    db = db_rules.rules(t)
    lag = [e for e in events if e.source is Source.KAFKA and e.component == "consumer-group"]
    config = [e for e in events if e.source is Source.APP_CONFIG]
    classified = {e.event_id: e for e in kafka_rules.classify_lag(lag, t)}
    classified.update({e.event_id: e for e in classify_config(config)})
    out = []
    for ev in events:
        if ev.event_id in classified:
            out.append(classified[ev.event_id])
        elif ev.source is Source.APP:
            out.append(_by_rules(ev, app_rules.RULES))
        elif ev.source is Source.DB:
            out.append(_by_rules(ev, db))
        elif ev.source is Source.KAFKA and ev.component in ("producer", "broker", "consumer"):
            out.append(_by_rules(ev, kafka_rules.RULES))
        else:  # Kafka messages: presence/absence is evidence for detectors, not an error
            out.append(replace(ev, severity=Severity.CONTEXT, error_code=None))
    return out
