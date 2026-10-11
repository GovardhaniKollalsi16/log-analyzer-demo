"""Seed configmap -> AppTopology: WHO is related (D26), never WHERE to look (D27).

Recognized keys (everything else is kept in `limits` if it looks like a limit):
  kafka.consumer.topics / kafka.consumer.group / kafka.producer.topics
  kafka.consumer.client.id / kafka.producer.client.id          (the app's own client IDs)
  upstream.apps / downstream.apps                              (comma-separated app names)
  upstream.<app>.kafka.client.ids / downstream.<app>.kafka.client.ids
  db.name                                                      (who: the app uses a DB)
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, List, Optional

from investigator.models import AppTopology, ConfigEntry, Event, TopicSubscription

_RELATED_IDS = re.compile(r"^(upstream|downstream)\.(?P<app>.+)\.kafka\.client\.ids$")
_LIMIT_SUFFIXES = (".ms", ".timeout", ".size", ".threads", ".retries", ".count", ".acks")


def _split(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_topology(app: str, entries: List[ConfigEntry]) -> AppTopology:
    cfg: Dict[str, str] = {e.key: e.value for e in entries if e.app == app}
    group = cfg.get("kafka.consumer.group", "")
    client_ids: Dict[str, str] = {}
    for own in ("kafka.consumer.client.id", "kafka.producer.client.id"):
        for cid in _split(cfg.get(own, "")):
            client_ids[cid] = app
    upstream, downstream = _split(cfg.get("upstream.apps", "")), _split(cfg.get("downstream.apps", ""))
    for key, value in cfg.items():
        m = _RELATED_IDS.match(key)
        # Only IDs of apps that are actually declared count; a stray key can't add an app.
        if m and m.group("app") in (upstream if key.startswith("upstream.") else downstream):
            for cid in _split(value):
                client_ids.setdefault(cid, m.group("app"))
    return AppTopology(
        app=app,
        consumes=[TopicSubscription(t, group) for t in _split(cfg.get("kafka.consumer.topics", ""))],
        produces=_split(cfg.get("kafka.producer.topics", "")),
        databases=_split(cfg.get("db.name", "")),
        limits={k: v for k, v in cfg.items() if k.endswith(_LIMIT_SUFFIXES)},
        upstream_apps=upstream,
        downstream_apps=downstream,
        client_ids=client_ids,
    )


def attribute_clients(events: List[Event], topology: Optional[AppTopology]) -> List[Event]:
    """Set `app` on Kafka client-log lines and lag rows ONLY when the config declares their client ID.
    Unmapped client IDs stay unattributed (app=None)."""
    if topology is None:
        return list(events)
    out = []
    for ev in events:
        cid = ev.attrs.get("client_id") or (ev.kafka.client_id if ev.kafka else None)
        if ev.app is None and cid and cid in topology.client_ids:
            ev = replace(ev, app=topology.client_ids[cid], attrs={**ev.attrs, "app_attribution": "seed config"})
        out.append(ev)
    return out
