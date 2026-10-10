"""`mocklogs`: tool-shaped commands over the synthetic world (MOCK).

Exit codes: 0 ok · 2 usage · 3 SSO session missing/expired · 4 forbidden (entitlement)
· 5 not found / unreachable · 6 no scenario loaded.
The scenario comes from MOCKLOGS_SCENARIO (+ optional MOCKLOGS_KNOBS JSON or @file),
set by the user/harness. It is never printed (R20).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from mocklogs import render, sso
from mocklogs.render import BANNER
from mocklogs.scenarios import load
from mocklogs.scenarios.base import ScenarioKnobs
from mocklogs.world import World

OK, USAGE, AUTH, FORBIDDEN, NOT_FOUND, NO_SCENARIO = 0, 2, 3, 4, 5, 6
SSO_EXPIRED = "error: SSO session expired or missing. Ask the user to run: mocklogs sso login"


@dataclass
class Result:
    code: int = OK
    out: List[str] = field(default_factory=list)
    err: List[str] = field(default_factory=list)


class Refusal(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- environment -------------------------------------------------------------

def knobs_from_env() -> ScenarioKnobs:
    raw = os.environ.get("MOCKLOGS_KNOBS", "").strip()
    if not raw:
        return ScenarioKnobs()
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    data = json.loads(raw)
    if "t0" in data:
        data["t0"] = parse_time(data["t0"])
    for key in ("access_denied", "omit_inputs"):
        if key in data:
            data[key] = frozenset(data[key])
    return ScenarioKnobs(**data)


def world_from_env() -> World:
    name = os.environ.get("MOCKLOGS_SCENARIO", "").strip()
    if not name:
        raise Refusal(NO_SCENARIO, "error: no MOCK scenario loaded (the user/harness sets MOCKLOGS_SCENARIO)")
    try:
        return load(name, knobs_from_env())
    except ValueError as e:
        raise Refusal(NO_SCENARIO, f"error: {e}") from None


def parse_time(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise argparse.ArgumentTypeError(f"time must include a zone (e.g. ...Z): {value}")
    return ts.astimezone(timezone.utc)


def require_sso() -> None:
    if sso.expires_at() is None:
        raise Refusal(AUTH, SSO_EXPIRED)


def check_access(world: World, key: str, message: str) -> None:
    if key in world.denied:
        raise Refusal(FORBIDDEN, message)


# --- app logs / config (kubectl shape) ----------------------------------------

def cmd_kubectl_logs(a, world: World) -> Result:
    kind, _, app = a.target.partition("/")
    if kind != "deploy" or not app:
        raise Refusal(USAGE, "error: only deploy/<name> targets are supported (MOCK)")
    if bool(a.instance) != bool(a.thread):
        raise Refusal(USAGE, "error: --instance and --thread must be given together (MOCK)")
    clusters = {d.cluster for d in world.deployments.values()}
    if a.context not in clusters:
        raise Refusal(NOT_FOUND, f'error: context "{a.context}" does not exist')
    check_access(world, f"logs:{app}",
                 f'Error from server (Forbidden): pods is forbidden: user "{sso.USER}" cannot get logs for '
                 f'deployment "{app}" in namespace "{a.namespace}" on cluster "{a.context}"')
    dep = world.deployments.get(app)
    if dep is None or dep.cluster != a.context or dep.namespace != a.namespace:
        raise Refusal(NOT_FOUND, f'Error from server (NotFound): deployments.apps "{app}" not found')
    lines = []
    for line in sorted((l for l in world.app_logs if l.app == app), key=lambda l: l.ts):
        ts = render.skewed(world, f"app:{app}", line.ts)
        if not render.in_window(ts, a.since_time, a.until_time):
            continue
        if a.instance and (line.instance != a.instance or line.thread != a.thread):
            continue
        text = render.app_kubectl(world, line, a.timestamps)
        if a.grep and a.grep not in text:
            continue
        lines.append((text, line.critical))
    return Result(out=lines)  # type: ignore[arg-type]


def cmd_kubectl_get(a, world: World) -> Result:
    if a.kind != "configmap":
        raise Refusal(USAGE, "error: only `get configmap` is supported (MOCK)")
    if a.output != "json":
        raise Refusal(USAGE, "error: only -o json is supported (MOCK)")
    clusters = {d.cluster for d in world.deployments.values()}
    if a.context not in clusters:
        raise Refusal(NOT_FOUND, f'error: context "{a.context}" does not exist')
    app = a.name[: -len("-config")] if a.name.endswith("-config") else a.name
    check_access(world, f"config:{app}",
                 f'Error from server (Forbidden): configmaps "{a.name}" is forbidden: user "{sso.USER}" cannot get '
                 f'resource "configmaps" in namespace "{a.namespace}" on cluster "{a.context}"')
    dep = world.deployments.get(app)
    if app not in world.configs or dep is None or dep.cluster != a.context or dep.namespace != a.namespace:
        raise Refusal(NOT_FOUND, f'Error from server (NotFound): configmaps "{a.name}" not found')
    doc = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": a.name, "namespace": a.namespace, "annotations": {"cluster": a.context}},
        "data": dict(sorted(world.configs[app].items())),
    }
    return Result(out=[(l, True) for l in json.dumps(doc, indent=4).split("\n")])  # type: ignore[arg-type]


# --- Kafka ---------------------------------------------------------------------

def require_bootstrap(a, world: World) -> None:
    if a.bootstrap_server != world.bootstrap:
        raise Refusal(NOT_FOUND, f"Error: Timed out waiting for a node assignment (bootstrap {a.bootstrap_server}).")


def require_topic(world: World, topic: str) -> None:
    check_access(world, f"kafka-topic:{topic}",
                 f"org.apache.kafka.common.errors.TopicAuthorizationException: Not authorized to access topics: [{topic}]")
    if topic not in world.topics:
        raise Refusal(NOT_FOUND, f"Error: Topic '{topic}' does not exist.")


def cmd_consumer_groups(a, world: World) -> Result:
    require_bootstrap(a, world)
    if not a.describe:
        raise Refusal(USAGE, "error: only --describe is supported (MOCK)")
    if a.all_groups:
        groups = [g for g in world.groups if f"kafka-group:{g.group}" not in world.denied]
    else:
        check_access(world, f"kafka-group:{a.group}",
                     f"org.apache.kafka.common.errors.GroupAuthorizationException: Not authorized to access group: {a.group}")
        groups = [g for g in world.groups if g.group == a.group]
        if not groups:
            raise Refusal(NOT_FOUND, f"Error: Consumer group '{a.group}' does not exist.")
    out = []
    for k in range(a.samples):
        at = world.now - timedelta(minutes=a.samples - 1 - k)
        if a.samples > 1:
            out.append((f"# sample {k + 1}/{a.samples} at {render.iso_ms(render.skewed(world, 'kafka', at))}", True))
        for g in (groups if a.all_groups else groups[:1]):
            out.append(("", True))
            out += [(l, True) for l in render.table(render.LAG_HEADER, render.lag_rows(world, [g], at))]
    return Result(out=out)  # type: ignore[arg-type]


def cmd_get_offsets(a, world: World) -> Result:
    require_bootstrap(a, world)
    require_topic(world, a.topic)
    out = []
    for p in range(world.topics[a.topic]):
        msgs = sorted((m for m in world.messages if m.topic == a.topic and m.partition == p), key=lambda m: m.offset)
        base = world.base_offsets[(a.topic, p)]
        end = base + len(msgs)
        if a.time == -1:
            off = end
        elif a.time == -2:
            off = base
        else:
            off = next((m.offset for m in msgs
                        if render.skewed(world, "kafka", m.ts).timestamp() * 1000 >= a.time), end)
        out.append((f"{a.topic}:{p}:{off}", True))
    return Result(out=out)  # type: ignore[arg-type]


def cmd_console_consumer(a, world: World) -> Result:
    require_bootstrap(a, world)
    require_topic(world, a.topic)
    if a.offset is not None and a.partition is None:
        raise Refusal(USAGE, "error: --offset requires --partition")
    if a.offset is None and a.partition is None and not a.from_beginning:
        raise Refusal(USAGE, "error: give --partition/--offset or --from-beginning (MOCK: no live tailing)")
    props: Dict[str, str] = {}
    for prop in a.property or []:
        key, _, value = prop.partition("=")
        props[key] = value
    msgs = sorted((m for m in world.messages if m.topic == a.topic), key=lambda m: (m.ts, m.partition, m.offset))
    if a.partition is not None:
        msgs = [m for m in msgs if m.partition == a.partition]
        if a.offset not in (None, "earliest"):
            start = (world.base_offsets[(a.topic, a.partition)] + len(msgs)) if a.offset == "latest" else int(a.offset)
            msgs = [m for m in msgs if m.offset >= start]
    out = []
    for m in msgs:
        text = render.console_message(world, m, props)
        if a.grep and a.grep not in text:
            continue
        out.append((text, True))
        if a.max_messages and len(out) >= a.max_messages:
            break
    return Result(out=out, err=[f"Processed a total of {len(out)} messages"])  # type: ignore[arg-type]


def cmd_kafka_logs(a, world: World) -> Result:
    require_bootstrap(a, world)
    require_topic(world, a.topic)
    out = []
    for line in sorted(world.kafka_logs, key=lambda l: l.ts):
        if line.component != a.component or line.topic != a.topic:
            continue
        if not render.in_window(render.skewed(world, "kafka", line.ts), a.since_time, a.until_time):
            continue
        out.append((render.kafka_log4j(world, line), line.critical))
    return Result(out=out)  # type: ignore[arg-type]


# --- DB ------------------------------------------------------------------------

def cmd_db_logs(a, world: World) -> Result:
    if a.host != world.db_host:
        raise Refusal(NOT_FOUND, f'error: could not translate host name "{a.host}" to address: Name or service not known')
    check_access(world, f"db:{a.db}",
                 f'error: permission denied: user "{sso.USER}" cannot read logs for database "{a.db}" on host "{a.host}"')
    if a.db != world.db_name:
        raise Refusal(NOT_FOUND, f'FATAL:  database "{a.db}" does not exist')
    out = []
    for line in sorted(world.db_logs, key=lambda l: l.ts):
        if line.db != a.db:
            continue
        if not render.in_window(render.skewed(world, "db", line.ts), a.since_time, a.until_time):
            continue
        text = render.db_text(world, line)
        if a.grep and a.grep not in text:
            continue
        out.append((text, line.critical))
    return Result(out=out)  # type: ignore[arg-type]


# --- user/harness-only commands (never in the agent's allowlist) -------------

def cmd_sso(a) -> Result:
    if a.action == "login":
        expires = sso.login(a.ttl_minutes)
        return Result(out=[("Opened SSO login (MOCK: no browser, no credentials).", True),
                           (f"Logged in as {sso.USER}. Session valid until {render.iso_ms(expires)}.", True)])
    if a.action == "logout":
        sso.logout()
        return Result(out=[("Logged out (MOCK).", True)])
    expires = sso.expires_at()
    if expires is None:
        return Result(code=AUTH, err=[SSO_EXPIRED])
    return Result(out=[(f"Logged in as {sso.USER}. Session valid until {render.iso_ms(expires)}.", True)])


def cmd_incident(a, world: World) -> Result:
    text = render.incident_text(world)
    return Result(out=[(l, True) for l in text.split("\n")[1:]])  # banner added by run()


# --- parser ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mocklogs", description="MOCK tool-shaped commands over synthetic incident data.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def window(sp):
        sp.add_argument("--since-time", type=parse_time)
        sp.add_argument("--until-time", type=parse_time, help="MOCK extension")

    def save(sp):
        sp.add_argument("--save-dir", help="also save raw output under <dir>/raw/ (MOCK extension)")

    s = sub.add_parser("sso", help="user-only: mock SSO session")
    s.add_argument("action", choices=["login", "logout", "status"])
    s.add_argument("--ttl-minutes", type=int, default=sso.DEFAULT_TTL_MINUTES)

    s = sub.add_parser("scenario", help="user/harness-only")
    s.add_argument("action", choices=["incident"])

    k = sub.add_parser("kubectl").add_subparsers(dest="kcmd", required=True)
    s = k.add_parser("logs")
    s.add_argument("target")
    s.add_argument("--context", required=True)
    s.add_argument("-n", "--namespace", required=True)
    s.add_argument("--timestamps", action="store_true")
    s.add_argument("--grep", help="MOCK extension")
    s.add_argument("--instance", help="MOCK extension")
    s.add_argument("--thread", help="MOCK extension")
    window(s), save(s)
    s = k.add_parser("get")
    s.add_argument("kind")
    s.add_argument("name")
    s.add_argument("--context", required=True)
    s.add_argument("-n", "--namespace", required=True)
    s.add_argument("-o", "--output", required=True)
    save(s)

    s = sub.add_parser("kafka-consumer-groups")
    s.add_argument("--bootstrap-server", required=True)
    s.add_argument("--describe", action="store_true")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--group")
    g.add_argument("--all-groups", action="store_true")
    s.add_argument("--samples", type=int, default=1, help="MOCK extension")
    save(s)

    s = sub.add_parser("kafka-get-offsets")
    s.add_argument("--bootstrap-server", required=True)
    s.add_argument("--topic", required=True)
    s.add_argument("--time", type=int, required=True, help="epoch ms, or -1 latest / -2 earliest")
    save(s)

    s = sub.add_parser("kafka-console-consumer")
    s.add_argument("--bootstrap-server", required=True)
    s.add_argument("--topic", required=True)
    s.add_argument("--partition", type=int)
    s.add_argument("--offset")
    s.add_argument("--from-beginning", action="store_true")
    s.add_argument("--max-messages", type=int)
    s.add_argument("--property", action="append")
    s.add_argument("--grep", help="MOCK extension")
    save(s)

    s = sub.add_parser("kafka").add_subparsers(dest="kafkacmd", required=True).add_parser("logs")
    s.add_argument("--bootstrap-server", required=True)
    s.add_argument("--component", choices=["broker", "producer", "consumer"], required=True)
    s.add_argument("--topic", required=True)
    window(s), save(s)

    s = sub.add_parser("db").add_subparsers(dest="dbcmd", required=True).add_parser("logs")
    s.add_argument("--host", required=True)
    s.add_argument("--db", required=True)
    s.add_argument("--grep", help="MOCK extension")
    window(s), save(s)
    return p


FETCH: Dict[str, Callable] = {
    "kubectl.logs": cmd_kubectl_logs,
    "kubectl.get": cmd_kubectl_get,
    "kafka-consumer-groups": cmd_consumer_groups,
    "kafka-get-offsets": cmd_get_offsets,
    "kafka-console-consumer": cmd_console_consumer,
    "kafka.logs": cmd_kafka_logs,
    "db.logs": cmd_db_logs,
}


def _key(a) -> str:
    sub = getattr(a, "kcmd", None) or getattr(a, "kafkacmd", None) or getattr(a, "dbcmd", None)
    return f"{a.cmd}.{sub}" if sub else a.cmd


def run(argv: List[str]) -> Result:
    """Execute one command. Handlers return (text, critical) lines; this returns plain text."""
    a = build_parser().parse_args(argv)
    key = _key(a)
    try:
        if key == "sso":
            res = cmd_sso(a)
            res.out = [text for text, _ in res.out]  # type: ignore[misc]
            return res
        world = world_from_env()
        if key == "scenario":
            res = cmd_incident(a, world)
            res.out = [text for text, _ in res.out]  # type: ignore[misc]
            return res
        require_sso()
        res = FETCH[key](a, world)
        salt = " ".join(x for x in argv if not x.startswith("--save-dir"))
        res.out = render.perturb(res.out, knobs_from_env(), salt=salt)  # type: ignore[arg-type]
        return res
    except Refusal as r:
        return Result(code=r.code, err=[r.message])


def _slug(argv: List[str]) -> str:
    words = []
    skip = False
    for x in argv:
        if skip:
            skip = False
            continue
        if x == "--save-dir":
            skip = True
            continue
        if x.startswith("--save-dir="):
            continue
        words.append(x)
    return re.sub(r"[^a-zA-Z0-9]+", "-", " ".join(words)).strip("-")[:60] or "output"


def save_output(save_dir: str, argv: List[str], res: Result) -> Path:
    raw = Path(save_dir) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    n = len(list(raw.glob("*.txt"))) + 1
    path = raw / f"{n:03d}-{_slug(argv)}.txt"
    path.write_text("\n".join([BANNER] + res.out + res.err) + "\n")
    meta = {"argv": ["mocklogs"] + argv, "exit_code": res.code,
            "saved_at": datetime.now(timezone.utc).isoformat()}
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    res = run(argv)
    print(BANNER)
    for line in res.out:
        print(line)
    sys.stdout.flush()  # the banner must precede any error text, even across stdout/stderr
    for line in res.err:
        print(line, file=sys.stderr)
    save_dir = getattr(build_parser().parse_args(argv), "save_dir", None)
    if save_dir:
        save_output(save_dir, argv, res)
    return res.code


if __name__ == "__main__":
    sys.exit(main())
