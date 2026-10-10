"""Application logs: optional kubectl RFC 3339 prefix + one JSON object per line."""

from __future__ import annotations

import json
import re
from typing import Optional, Tuple, Union

from investigator import normalize
from investigator.adapters.base import RawOutput
from investigator.models import Event, Ids, ParseIssue, ParseIssueKind, RawRecord, Source
from investigator.parsing import ParseResult, content_lines

_PREFIX = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\S+Z) (?P<body>\{.*)$")
REQUIRED = ("ts", "level", "app", "msg")


def parse_record(text: str, command: str, line_no: int) -> Union[Event, ParseIssue]:
    """Parse one app log line (with or without the kubectl prefix)."""
    m = _PREFIX.match(text)
    body = m.group("body") if m else text
    try:
        obj = json.loads(body)
        if not isinstance(obj, dict):
            raise ValueError("not a JSON object")
    except ValueError as e:
        return ParseIssue(Source.APP, line_no, ParseIssueKind.MALFORMED, text, str(e))
    missing = [k for k in REQUIRED if not obj.get(k)]
    if missing:
        return ParseIssue(Source.APP, line_no, ParseIssueKind.MISSING_FIELD, text, f"missing {missing}")
    lvl = normalize.level(str(obj["level"]))
    if lvl is None:
        return ParseIssue(Source.APP, line_no, ParseIssueKind.MALFORMED, text, f"unknown level {obj['level']!r}")
    ts_raw = str(obj["ts"])
    ts = normalize.parse_ts(ts_raw) or (normalize.parse_ts(m.group("ts")) if m else None)
    instance: Optional[str] = obj.get("instance") or None
    thread: Optional[str] = obj.get("thread") if instance else None  # threads are only meaningful per instance
    attrs = {}
    if isinstance(obj.get("error"), dict):
        attrs["error"] = obj["error"]
    return Event(
        event_id=normalize.event_id(Source.APP, json.dumps(obj, sort_keys=True, separators=(",", ":"))),
        source=Source.APP,
        level=lvl,
        message=str(obj["msg"]),
        ts_raw=ts_raw,
        ts_utc=ts,
        app=str(obj["app"]),
        cluster=obj.get("cluster") or None,
        namespace=obj.get("namespace") or None,
        instance=instance,
        thread=thread,
        logger=obj.get("logger") or None,
        ids=Ids(correlation_id=obj.get("correlation_id") or None, trace_id=obj.get("trace_id") or None,
                request_id=obj.get("request_id") or None),
        keys=normalize.business_keys(obj),
        attrs=attrs,
        raw_refs=[RawRecord(Source.APP, command, line_no, text)],
    )


def parse(out: RawOutput) -> ParseResult:
    res = ParseResult()
    command = " ".join(out.argv)
    for n, line in content_lines(out):
        rec = parse_record(line, command, n)
        (res.events if isinstance(rec, Event) else res.issues).append(rec)  # type: ignore[arg-type]
    return res


def split_seed(text: str) -> Tuple[Optional[Event], Optional[ParseIssue]]:
    rec = parse_record(text, "incident seed", 1)
    return (rec, None) if isinstance(rec, Event) else (None, rec)

