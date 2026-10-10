"""DB logs: postgres-style `log_line_prefix` text. Business keys come from statement columns only."""

from __future__ import annotations

import re
from typing import Dict

from investigator import normalize
from investigator.adapters.base import RawOutput
from investigator.models import Event, ParseIssue, ParseIssueKind, RawRecord, Source
from investigator.parsing import ParseResult, content_lines

_LINE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? \S+) \[(?P<pid>\d+)\] "
                   r"app=(?P<app>\S*) user=(?P<user>\S*) db=(?P<db>\S*) (?P<sev>[A-Z]+):\s+(?P<msg>.*)$")
_INSERT = re.compile(r"INSERT INTO \S+ \((?P<cols>[^)]*)\) VALUES \((?P<vals>[^)]*)\)", re.I)
_WHERE = re.compile(r"\b(?P<col>\w+_id)\s*=\s*'(?P<val>[^']*)'", re.I)


def statement_keys(msg: str) -> Dict[str, str]:
    keys: Dict[str, str] = {}
    m = _INSERT.search(msg)
    if m:
        cols = [c.strip() for c in m.group("cols").split(",")]
        vals = [v.strip().strip("'") for v in m.group("vals").split(",")]
        if len(cols) == len(vals):
            keys.update({c: v for c, v in zip(cols, vals) if c.endswith("_id")})
    for w in _WHERE.finditer(msg):
        keys.setdefault(w.group("col"), w.group("val"))
    return normalize.business_keys(keys)


def parse(out: RawOutput) -> ParseResult:
    res = ParseResult()
    command = " ".join(out.argv)
    for n, line in content_lines(out):
        m = _LINE.match(line)
        lvl = normalize.level(m.group("sev")) if m else None
        if not m or lvl is None:
            res.issues.append(ParseIssue(Source.DB, n, ParseIssueKind.MALFORMED, line, "not a DB log line"))
            continue
        res.events.append(Event(
            event_id=normalize.event_id(Source.DB, line),
            source=Source.DB,
            level=lvl,
            message=m.group("msg"),
            ts_raw=m.group("ts"),
            ts_utc=normalize.parse_ts(m.group("ts")),
            app=m.group("app") or None,
            component="db",
            keys=statement_keys(m.group("msg")),
            attrs={"pid": int(m.group("pid")), "user": m.group("user"), "db": m.group("db"),
                   "severity": m.group("sev")},
            raw_refs=[RawRecord(Source.DB, command, n, line)],
        ))
    return res
