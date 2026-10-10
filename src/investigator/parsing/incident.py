"""The incident message (D23): `INCIDENT` / `seed:` / `app:` / `app[<name>]:` / `kafka:` / `db:`.

Absent lines stay absent (no input, no access, D22). Values are taken exactly as written.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from investigator.correlation_keys import KeyRule, choose_business_key
from investigator.models import Incident, Location, Seed
from investigator.parsing.app_logs import split_seed

_LINE = re.compile(r"^(?P<tag>seed|app|app\[(?P<name>[^\]]+)\]|kafka|db):\s*(?P<rest>.*)$")


class IncidentError(ValueError):
    pass


def _pairs(rest: str) -> Dict[str, str]:
    out = {}
    for token in rest.split():
        key, sep, value = token.partition("=")
        if sep and value:
            out[key] = value
    return out


def parse_incident(text: str, rules: Optional[List[KeyRule]] = None) -> Incident:
    seed_event = None
    app: Optional[Location] = None
    related: Dict[str, Location] = {}
    kafka: Dict[str, str] = {}
    db: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "INCIDENT":
            continue
        m = _LINE.match(line)
        if not m:
            continue  # unknown lines are ignored, never interpreted
        tag, rest = m.group("tag"), m.group("rest")
        if tag == "seed":
            seed_event, issue = split_seed(rest)
            if issue is not None:
                raise IncidentError(f"seed line is not a valid app log record: {issue.detail}")
        elif tag == "app" or m.group("name"):
            pairs = _pairs(rest)
            if "cluster" in pairs and "namespace" in pairs:
                loc = Location(pairs["cluster"], pairs["namespace"])
                if m.group("name"):
                    related[m.group("name")] = loc
                else:
                    app = loc
        elif tag == "kafka":
            kafka = _pairs(rest)
        elif tag == "db":
            db = _pairs(rest)
    if seed_event is None:
        raise IncidentError("the incident has no seed line; there is nothing to investigate")
    if seed_event.ts_utc is None:
        raise IncidentError("the seed line has no parseable timestamp")
    key = choose_business_key(seed_event.logger, seed_event.keys, rules or [])
    seed = Seed(
        event_id=seed_event.event_id,
        app=seed_event.app or "",
        ts_utc=seed_event.ts_utc,
        cluster=seed_event.cluster,
        namespace=seed_event.namespace,
        instance=seed_event.instance,
        thread=seed_event.thread,
        logger=seed_event.logger,
        correlation_id=seed_event.ids.correlation_id,
        keys=dict(seed_event.keys),
        business_key=key,
    )
    topics = [t for t in kafka.get("topics", "").split(",") if t]
    return Incident(
        seed=seed,
        seed_event=seed_event,
        app=app,
        related_apps=related,
        kafka_bootstrap=kafka.get("bootstrap") if topics else None,
        kafka_topics=topics if kafka.get("bootstrap") else [],
        kafka_group=kafka.get("group") if kafka.get("bootstrap") else None,
        db_host=db.get("host") if db.get("name") else None,
        db_name=db.get("name") if db.get("host") else None,
    )
