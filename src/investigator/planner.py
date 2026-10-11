"""`investigator plan`: given the incident and what's already in the workdir, list the next fetches.

Deterministic and idempotent. Run it, execute the steps it returns, and run it again
until `done`. The order follows PROPOSAL §1 / the coordinator skill:
  1 seed app logs -> 2 seed config -> 3 Kafka (per incident topic: offsets, messages,
  producer/consumer/broker logs) -> 4 related apps declared in the seed config (one hop)
  -> 5 DB.
WHERE comes only from the incident (D27). WHO comes only from the seed config (D26).
A missing required input becomes a `missing_input` gap, never a guessed command (D22).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from investigator.adapters.base import RawOutput
from investigator.config_model import build_topology
from investigator.models import (
    AppTopology,
    CoverageGap,
    Direction,
    FetchPlan,
    FetchStep,
    GapReason,
    Incident,
    Source,
)
from investigator.parsing import ParseResult

TOOL = "mocklogs"                     # the CLI being driven; real integrations swap this
WINDOW_BEFORE = timedelta(minutes=10)  # coordinator default, to be tuned
WINDOW_AFTER = timedelta(minutes=2)
THREAD_WINDOW = timedelta(minutes=1)   # D17
MAX_MESSAGES = 500
MAX_FOLLOWUPS_PER_APP = 5              # R14: bound fan-out from one related app
AUTH_RETRIES = 1                       # skill: after the user re-authenticates, retry once


def _rfc(ts) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _key(argv: List[str]) -> Tuple[str, ...]:
    """Identity of a command, ignoring where its output is saved."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--save-dir":
            skip = True
            continue
        out.append(a)
    return tuple(out)


class _Planner:
    def __init__(self, incident: Incident, parsed: ParseResult, outputs: List[RawOutput], workdir: str):
        self.inc, self.parsed, self.workdir = incident, parsed, workdir
        self.attempts: Dict[Tuple[str, ...], List[int]] = {}
        for out in outputs:
            self.attempts.setdefault(_key(out.argv), []).append(out.exit_code)
        self.steps: List[FetchStep] = []
        self.gaps: List[CoverageGap] = []
        seed = incident.seed
        self.since = _rfc(seed.ts_utc - WINDOW_BEFORE)
        self.until = _rfc(seed.ts_utc + WINDOW_AFTER)
        self.bk_name = seed.business_key
        self.bk = seed.keys.get(seed.business_key) if seed.business_key else None

    # --- bookkeeping ---------------------------------------------------------------
    def want(self, component: Source, target: str, argv: List[str], reason: str,
             direction: Direction = Direction.SEED) -> Optional[int]:
        """Plan `argv` unless it already ran. Returns its exit code if it ran (None if pending)."""
        full = [TOOL] + argv + ["--save-dir", self.workdir]
        runs = self.attempts.get(_key(full), [])
        retry_auth = runs and runs[-1] == 3 and len(runs) <= AUTH_RETRIES
        if not runs or retry_auth:
            self.steps.append(FetchStep(order=len(self.steps) + 1, component=component, target=target,
                                        argv=full, reason=reason, direction=direction))
            return None
        return runs[-1]

    def gap(self, component: Source, target: str, detail: str) -> None:
        self.gaps.append(CoverageGap(component, target, GapReason.MISSING_INPUT, detail))

    # --- 1. seed app logs ----------------------------------------------------------
    def seed_logs(self) -> None:
        inc, seed = self.inc, self.inc.seed
        if inc.app is None:
            self.gap(Source.APP, seed.app, "app cluster/namespace (incident `app:` line)")
            return
        base = ["kubectl", "logs", f"deploy/{seed.app}", "--context", inc.app.cluster, "-n", inc.app.namespace,
                "--timestamps", f"--since-time={self.since}", f"--until-time={self.until}"]
        if seed.correlation_id:
            self.want(Source.APP, seed.app, base + ["--grep", seed.correlation_id],
                      "seed app: its own correlation ID")
        elif self.bk:
            self.want(Source.APP, seed.app, base + ["--grep", self.bk], f"seed app: business key {self.bk_name}")
        else:
            self.want(Source.APP, seed.app, base, "seed app: time window only (no correlation ID or business key)")
        if seed.instance and seed.thread:
            self.want(Source.APP, seed.app,
                      ["kubectl", "logs", f"deploy/{seed.app}", "--context", inc.app.cluster, "-n", inc.app.namespace,
                       "--timestamps", f"--since-time={_rfc(seed.ts_utc - THREAD_WINDOW)}",
                       f"--until-time={_rfc(seed.ts_utc + THREAD_WINDOW)}",
                       "--instance", seed.instance, "--thread", seed.thread],
                      "seed app: the seed's thread segment (ID-less lines of the same unit of work)")

    # --- 2. seed config ----------------------------------------------------------------
    def seed_config(self) -> Tuple[Optional[AppTopology], bool]:
        """(topology, settled): settled means the config step finished, successfully or not."""
        inc, seed = self.inc, self.inc.seed
        if inc.app is None:
            self.gap(Source.APP_CONFIG, f"{seed.app}-config", "app cluster/namespace (incident `app:` line)")
            return None, True
        code = self.want(Source.APP_CONFIG, f"{seed.app}-config",
                         ["kubectl", "get", "configmap", f"{seed.app}-config", "--context", inc.app.cluster,
                          "-n", inc.app.namespace, "-o", "json"],
                         "seed app config: who is related, topic direction, limits")
        if code is None:
            return None, False  # planned now, or awaiting a re-authenticated retry
        return (build_topology(seed.app, self.parsed.config) if code == 0 else None), True

    # --- 3. Kafka ------------------------------------------------------------------
    def kafka(self, topo: Optional[AppTopology]) -> None:
        inc = self.inc
        if not inc.kafka_bootstrap or not inc.kafka_topics:
            self.gap(Source.KAFKA, "kafka", "Kafka bootstrap/topics (incident `kafka:` line)")
            return
        boot = ["--bootstrap-server", inc.kafka_bootstrap]
        consumed = {s.topic for s in topo.consumes} if topo else set()
        produced = set(topo.produces) if topo else set()
        start_ms = str(int((inc.seed.ts_utc - WINDOW_BEFORE).timestamp() * 1000))
        for topic in inc.kafka_topics:
            direction = ("incoming" if topic in consumed else "outgoing" if topic in produced
                         else "direction unknown")
            # 1/2: incoming/outgoing messages carrying the business key
            if not self.bk:
                self.gap(Source.KAFKA, f"topic:{topic}", "business key for the message search")
            else:
                code = self.want(Source.KAFKA, f"topic:{topic}",
                                 ["kafka-get-offsets", *boot, "--topic", topic, "--time", start_ms],
                                 f"messages on {topic}: offsets at window start")
                if code == 0:
                    for (t, p), offset in sorted(self.parsed.offsets.items()):
                        if t != topic:
                            continue
                        self.want(Source.KAFKA, f"topic:{topic}",
                                  ["kafka-console-consumer", *boot, "--topic", topic, "--partition", str(p),
                                   "--offset", str(offset), "--max-messages", str(MAX_MESSAGES),
                                   "--property", "print.headers=true", "--property", "print.timestamp=true",
                                   "--property", "print.partition=true", "--property", "print.offset=true",
                                   "--grep", self.bk],
                                  f"{direction} messages on {topic}-{p} with {self.bk_name}={self.bk}")
            # 3/4: retries, topic errors and connection timeouts (unfiltered client and broker logs)
            for component in ("producer", "consumer", "broker"):
                self.want(Source.KAFKA, f"topic:{topic}",
                          ["kafka", "logs", *boot, "--component", component, "--topic", topic,
                           f"--since-time={self.since}", f"--until-time={self.until}"],
                          f"{component} logs for {topic}: retries, errors, timeouts")

    # --- 4. related apps (one hop) ----------------------------------------------------
    def related(self, topo: Optional[AppTopology], config_settled: bool) -> None:
        inc, seed = self.inc, self.inc.seed
        if topo is None:
            if config_settled:
                self.gap(Source.APP, "related apps", "upstream/downstream apps (seed config unavailable)")
            return  # config not fetched yet: decided next round
        for direction, apps in ((Direction.UPSTREAM, topo.upstream_apps), (Direction.DOWNSTREAM, topo.downstream_apps)):
            for app in apps:
                if app == seed.app:
                    continue
                loc = inc.related_apps.get(app)
                if loc is None:
                    self.gap(Source.APP, app, f"cluster/namespace for {app} (incident `app[{app}]:` line)")
                    continue
                if not self.bk:
                    self.gap(Source.APP, app, "business key for searching a related app")
                    continue
                base = ["kubectl", "logs", f"deploy/{app}", "--context", loc.cluster, "-n", loc.namespace,
                        "--timestamps", f"--since-time={self.since}", f"--until-time={self.until}"]
                code = self.want(Source.APP, app, base + ["--grep", self.bk],
                                 f"{direction.value} app {app}: business key {self.bk_name}", direction)
                if code != 0:
                    continue
                hits = [e for e in self.parsed.events
                        if e.source is Source.APP and e.app == app and e.keys.get(self.bk_name) == self.bk]
                corr_ids = sorted({e.ids.correlation_id for e in hits if e.ids.correlation_id})
                threads = sorted({(e.instance, e.thread) for e in hits if e.instance and e.thread})
                for cid in corr_ids[:MAX_FOLLOWUPS_PER_APP]:
                    self.want(Source.APP, app, base + ["--grep", cid],
                              f"{direction.value} app {app}: its own correlation ID {cid}", direction)
                for instance, thread in threads[:MAX_FOLLOWUPS_PER_APP]:
                    times = [e.ts_utc for e in hits if (e.instance, e.thread) == (instance, thread) and e.ts_utc]
                    self.want(Source.APP, app,
                              ["kubectl", "logs", f"deploy/{app}", "--context", loc.cluster, "-n", loc.namespace,
                               "--timestamps", f"--since-time={_rfc(min(times) - THREAD_WINDOW)}",
                               f"--until-time={_rfc(max(times) + THREAD_WINDOW)}",
                               "--instance", instance, "--thread", thread],
                              f"{direction.value} app {app}: thread segment {instance}/{thread}", direction)

    # --- 5. DB --------------------------------------------------------------------------
    def db(self) -> None:
        inc = self.inc
        if not inc.db_host or not inc.db_name:
            self.gap(Source.DB, "db", "DB host/name (incident `db:` line)")
            return
        argv = ["db", "logs", "--host", inc.db_host, "--db", inc.db_name,
                f"--since-time={self.since}", f"--until-time={self.until}"]
        if self.bk:
            self.want(Source.DB, f"{inc.db_host}/{inc.db_name}", argv + ["--grep", self.bk],
                      f"DB statements with {self.bk_name}={self.bk}")
        else:
            self.want(Source.DB, f"{inc.db_host}/{inc.db_name}", argv + ["--grep", inc.seed.app],
                      "DB sessions of the seed app (no business key)")

    def run(self) -> FetchPlan:
        self.seed_logs()
        topo, config_settled = self.seed_config()
        self.kafka(topo)
        self.related(topo, config_settled)
        self.db()
        done = not self.steps
        return FetchPlan(steps=self.steps, gaps=self.gaps, done=done,
                         stop_reason="no remaining fetches" if done else None)


def plan(incident: Incident, parsed: ParseResult, outputs: List[RawOutput], workdir: str) -> FetchPlan:
    return _Planner(incident, parsed, outputs, workdir).run()


def topology_of(incident: Incident, parsed: ParseResult) -> Optional[AppTopology]:
    if not any(c.app == incident.seed.app for c in parsed.config):
        return None
    return build_topology(incident.seed.app, parsed.config)

