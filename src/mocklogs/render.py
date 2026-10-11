"""Turn World records into text shaped like the real tools, plus the MOCK banner."""

from __future__ import annotations

import json
import zlib
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from mocklogs.scenarios.base import ScenarioKnobs, make_rng
from mocklogs.world import AppLogLine, DbLogLine, GroupInfo, KafkaLogLine, KafkaMessage, World

BANNER = "# MOCK DATA — synthetic, not from any real system"

Line = Tuple[str, bool]  # (text, critical)


# --- time --------------------------------------------------------------------

def iso_ms(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def kubectl_prefix(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond:06d}000Z"


# --- per-format renderers ----------------------------------------------------

def app_json(world: World, line: AppLogLine) -> str:
    dep = world.deployments[line.app]
    ts = line.ts
    obj = {
        "ts": iso_ms(ts),
        "level": line.level,
        "cluster": dep.cluster,
        "namespace": dep.namespace,
        "app": line.app,
        "instance": line.instance,
        "thread": line.thread,
        "logger": line.logger,
    }
    if line.correlation_id:
        obj["correlation_id"] = line.correlation_id
    obj.update(line.keys)
    obj["msg"] = line.msg
    if line.error:
        obj["error"] = line.error
    return json.dumps(obj, separators=(",", ":"))


def app_kubectl(world: World, line: AppLogLine, timestamps: bool) -> str:
    body = app_json(world, line)
    if not timestamps:
        return body
    return f"{kubectl_prefix(line.ts)} {body}"


def kafka_log4j(world: World, line: KafkaLogLine) -> str:
    ts = line.ts
    stamp = ts.strftime("%Y-%m-%d %H:%M:%S,") + f"{ts.microsecond // 1000:03d}"
    return f"[{stamp}] {line.level} {line.text} ({line.logger})"


def db_text(world: World, line: DbLogLine) -> str:
    ts = line.ts
    stamp = ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d} UTC"
    return f"{stamp} [{line.pid}] app={line.app} user={line.user} db={line.db} {line.severity}:  {line.msg}"


def console_message(world: World, msg: KafkaMessage, props: Dict[str, str]) -> str:
    parts = []
    if props.get("print.timestamp") == "true":
        ms = int(msg.ts.timestamp() * 1000)
        parts.append(f"CreateTime:{ms}")
    if props.get("print.partition") == "true":
        parts.append(f"Partition:{msg.partition}")
    if props.get("print.offset") == "true":
        parts.append(f"Offset:{msg.offset}")
    if props.get("print.headers") == "true":
        parts.append(",".join(f"{k}:{v}" for k, v in msg.headers.items()) or "NO_HEADERS")
    parts.append(json.dumps(msg.value, separators=(",", ":")))
    return "\t".join(parts)


def lag_rows(world: World, groups: Sequence[GroupInfo], at: datetime) -> List[List[str]]:
    rows = []
    for g in groups:
        for p in range(world.topics[g.topic]):
            end = world.base_offsets[(g.topic, p)] + sum(
                1 for m in world.messages if m.topic == g.topic and m.partition == p and m.ts <= at)
            current = end  # consumers keep up in this world unless a scenario says otherwise
            rows.append([g.group, g.topic, str(p), str(current), str(end), str(end - current),
                         g.consumer_id, g.host, g.client_id])
    return rows


def table(header: List[str], rows: List[List[str]]) -> List[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)]
    fmt = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()  # noqa: E731
    return [fmt(header)] + [fmt(r) for r in rows]


LAG_HEADER = ["GROUP", "TOPIC", "PARTITION", "CURRENT-OFFSET", "LOG-END-OFFSET", "LAG",
              "CONSUMER-ID", "HOST", "CLIENT-ID"]


def incident_text(world: World) -> str:
    inc = world.incident
    out = [BANNER, "INCIDENT", f"seed: {app_json(world, inc.seed_record)}"]
    if inc.app:
        out.append(f"app:    cluster={inc.app[0]} namespace={inc.app[1]}")
    for name, (cluster, ns) in sorted(inc.related_apps.items()):
        out.append(f"app[{name}]: cluster={cluster} namespace={ns}")
    if inc.kafka_bootstrap:
        line = f"kafka:  bootstrap={inc.kafka_bootstrap} topics={','.join(inc.kafka_topics)}"
        out.append(line + (f" group={inc.kafka_group}" if inc.kafka_group else ""))
    if inc.db_host and inc.db_name:
        out.append(f"db:     host={inc.db_host} name={inc.db_name}")
    return "\n".join(out)


# --- perturbation knobs (non-critical lines only) ----------------------------

def perturb(lines: Iterable[Line], knobs: ScenarioKnobs, salt: str) -> List[str]:
    rng = make_rng(knobs.seed, f"perturb:{zlib.crc32(salt.encode())}")
    out: List[str] = []
    for text, critical in lines:
        if not critical and knobs.drop_rate and rng.random() < knobs.drop_rate:
            continue
        if not critical and knobs.malformed_rate and rng.random() < knobs.malformed_rate:
            text = text[: max(1, int(len(text) * rng.uniform(0.2, 0.7)))]
        out.append(text)
        if knobs.dup_rate and rng.random() < knobs.dup_rate:
            out.append(text)
    if knobs.shuffle:
        rng.shuffle(out)
    return out


def in_window(ts: datetime, since: Optional[datetime], until: Optional[datetime]) -> bool:
    return (since is None or ts >= since) and (until is None or ts <= until)
