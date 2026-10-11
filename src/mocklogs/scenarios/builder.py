"""Shared machinery for scenario generators 2–4 (scenario 1 predates it and is left as approved).

A scenario declares its default names (roles -> names), derived names, apps and topics, then
adds records through these helpers. Every record that carries the scenario's evidence is
marked `critical=True`, so perturbation knobs (drop/malformed) never remove the story.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from mocklogs.scenarios.base import ScenarioKnobs, make_rng, resolve_denied, resolve_names, short_id
from mocklogs.world import (AppLogLine, DbLogLine, Deployment, GroupInfo, Incident, KafkaLogLine, KafkaMessage,
                            World)


class Builder:
    def __init__(self, knobs: ScenarioKnobs, salt: str, defaults: Dict[str, str],
                 derived: Dict[str, Callable[[Dict[str, str]], str]], app_roles: List[str]):
        self.knobs = knobs
        self.rng = make_rng(knobs.seed, salt)
        n = resolve_names({**defaults, **{k: "" for k in derived}}, knobs)
        for key, derive in derived.items():
            if key not in knobs.names:
                n[key] = derive(n)
        self.n = n
        self.app_roles = app_roles
        self.deployments = {
            n[r]: Deployment(app=n[r], cluster=n["cluster"], namespace=n["namespace"],
                             instances=[f"{n[r]}-{short_id(self.rng, '', 5)}-{i}" for i in range(2)])
            for r in app_roles
        }
        self.app_logs: List[AppLogLine] = []
        self.kafka_logs: List[KafkaLogLine] = []
        self.db_logs: List[DbLogLine] = []
        self.messages: List[KafkaMessage] = []
        self.topics: Dict[str, int] = {}
        self.base_offsets: Dict[Tuple[str, int], int] = {}
        self.next_offset: Dict[Tuple[str, int], int] = {}
        self.groups: List[GroupInfo] = []
        self.configs: Dict[str, Dict[str, str]] = {}

    # --- names & time ------------------------------------------------------------------
    def at(self, sec: float) -> datetime:
        return self.knobs.t0 + timedelta(seconds=sec)

    def inst(self, role: str, i: int) -> str:
        return self.deployments[self.n[role]].instances[i % 2]

    def producer_client(self, role: str) -> str:
        return f"{self.n[role]}-producer-1"

    def consumer_client(self, role: str) -> str:
        return f"{self.n[role]}-consumer-1"

    def cid(self) -> str:
        return short_id(self.rng, "c-")

    # --- records -----------------------------------------------------------------------------
    def topic(self, role: str, partitions: int, base: int) -> None:
        t = self.n[role]
        self.topics[t] = partitions
        for p in range(partitions):
            self.base_offsets[(t, p)] = base + 300 * p
            self.next_offset[(t, p)] = base + 300 * p

    def app(self, sec, level, role, i, thread, logger, msg, corr=None, error=None, critical=False, keys=None):
        self.app_logs.append(AppLogLine(self.at(sec), level, self.n[role], self.inst(role, i), thread, logger, msg,
                                        corr, error, critical, dict(keys or {})))

    def klog(self, sec, level, component, topic_role, text, logger, critical=False):
        self.kafka_logs.append(KafkaLogLine(self.at(sec), level, component, self.n[topic_role], text, logger, critical))

    def client_line(self, sec, level, role, i, component, topic_role, text, logger, critical=True):
        """A Kafka client line: logged by the app (network/consumer thread) AND visible in `kafka logs`."""
        client = self.producer_client(role) if component == "producer" else self.consumer_client(role)
        thread = (f"kafka-producer-network-thread | {client}" if component == "producer"
                  else f"{client}-poll")
        self.app(sec, level, role, i, thread, logger, text, critical=critical)
        self.klog(sec, level, component, topic_role, text, logger, critical=critical)

    def produce(self, topic_role, partition, sec, corr, producer_role, value) -> int:
        t = self.n[topic_role]
        off = self.next_offset[(t, partition)]
        self.next_offset[(t, partition)] = off + 1
        self.messages.append(KafkaMessage(t, partition, off, self.at(sec),
                                          {"correlation_id": corr, "producer_app": self.n[producer_role]}, value))
        return off

    def db(self, sec, pid, role, severity, msg, critical=False):
        self.db_logs.append(DbLogLine(self.at(sec), pid, self.n[role] if role else "", self.n.get("db_user", "app"),
                                      self.n["db_name"], severity, msg, critical))

    def group(self, group_role, topic_role, consumer_role, host):
        client = self.consumer_client(consumer_role)
        self.groups.append(GroupInfo(self.n[group_role], self.n[topic_role], client,
                                     f"{client}-{short_id(self.rng, '', 8)}", host))

    def health_noise(self, until_s: int = 360) -> None:
        for role in self.app_roles:
            for k, sec in enumerate(range(0, until_s + 1, 60)):
                self.app(sec + self.rng.uniform(0, 2), "INFO", role, k, "health-1", "app.Health", "Health check OK")

    # --- world ---------------------------------------------------------------------------------
    def build(self, seed: AppLogLine, related_roles: List[str], kafka_topic_roles: List[str],
              kafka_group_role: Optional[str], with_db: bool) -> World:
        n, omit = self.n, self.knobs.omit_inputs
        loc = (n["cluster"], n["namespace"])
        incident = Incident(
            seed_record=seed,
            app=None if "app" in omit else loc,
            related_apps={} if "related" in omit else {n[r]: loc for r in related_roles},
            kafka_bootstrap=None if "kafka" in omit else n["bootstrap"],
            kafka_topics=[] if "kafka" in omit else [n[t] for t in kafka_topic_roles],
            kafka_group=None if ("kafka" in omit or not kafka_group_role) else n[kafka_group_role],
            db_host=None if ("db" in omit or not with_db) else n["db_host"],
            db_name=None if ("db" in omit or not with_db) else n["db_name"],
        )
        return World(
            now=seed.ts + timedelta(minutes=2), deployments=self.deployments, configs=self.configs,
            bootstrap=n["bootstrap"], topics=self.topics, base_offsets=self.base_offsets, messages=self.messages,
            groups=self.groups, app_logs=self.app_logs, kafka_logs=self.kafka_logs, db_host=n["db_host"],
            db_name=n["db_name"], db_logs=self.db_logs, incident=incident, denied=resolve_denied(self.knobs, n),
        )


COMMON_NAMES = {
    "cluster": "cluster-a",
    "namespace": "apps",
    "bootstrap": "kafka-a:9092",
    "db_host": "db-a",
    "db_name": "appdb",
}
