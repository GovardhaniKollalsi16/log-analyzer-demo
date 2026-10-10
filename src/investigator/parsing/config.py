"""App config: `kubectl get configmap -o json`. Each key becomes a ConfigEntry and a citable Event."""

from __future__ import annotations

import json

from investigator import normalize
from investigator.adapters.base import RawOutput
from investigator.models import ConfigEntry, Event, Level, ParseIssue, ParseIssueKind, RawRecord, Source
from investigator.parsing import ParseResult, content_lines


def _arg(argv, *names):
    for i, a in enumerate(argv):
        if a in names and i + 1 < len(argv):
            return argv[i + 1]
    return None


def parse(out: RawOutput) -> ParseResult:
    res = ParseResult()
    command = " ".join(out.argv)
    lines = list(content_lines(out))
    body = "\n".join(text for _, text in lines)
    first = lines[0][0] if lines else 1
    try:
        doc = json.loads(body)
        data = doc["data"]
        meta = doc.get("metadata", {})
        name = meta["name"]
        if not isinstance(data, dict):
            raise ValueError("data is not an object")
    except (ValueError, KeyError, TypeError) as e:
        res.issues.append(ParseIssue(Source.APP_CONFIG, first, ParseIssueKind.MALFORMED, body[:200], str(e)))
        return res
    app = name[: -len("-config")] if name.endswith("-config") else name
    cluster = (meta.get("annotations") or {}).get("cluster") or _arg(out.argv, "--context")
    namespace = meta.get("namespace") or _arg(out.argv, "-n", "--namespace")
    for key, value in sorted(data.items()):
        ref = RawRecord(Source.APP_CONFIG, command, first, f"{key}={value}")
        res.config.append(ConfigEntry(app=app, key=key, value=str(value), raw_ref=ref))
        res.events.append(Event(
            event_id=normalize.event_id(Source.APP_CONFIG, f"{cluster}|{namespace}|{app}|{key}={value}"),
            source=Source.APP_CONFIG,
            level=Level.INFO,
            message=f"{key}={value}",
            ts_raw="",
            ts_utc=None,  # config is current state, with no change history (D20)
            app=app,
            cluster=cluster,
            namespace=namespace,
            attrs={"key": key, "value": str(value)},
            raw_refs=[ref],
        ))
    return res
