"""Kafka: consumer-group tables, offsets, console-consumer messages, broker/client log4j lines."""

from __future__ import annotations

import json
import re
from typing import Optional

from investigator import normalize
from investigator.adapters.base import RawOutput
from investigator.models import Event, Ids, KafkaRef, Level, ParseIssue, ParseIssueKind, RawRecord, Source
from investigator.parsing import ParseResult, content_lines

GROUP_COLUMNS = ["GROUP", "TOPIC", "PARTITION", "CURRENT-OFFSET", "LOG-END-OFFSET", "LAG",
                 "CONSUMER-ID", "HOST", "CLIENT-ID"]
_SAMPLE = re.compile(r"^# sample (\d+)/(\d+) at (\S+)$")
_LOG4J = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\] (?P<level>[A-Z]+) "
                    r"(?P<text>.*) \((?P<logger>[\w.$]+)\)$")
_CLIENT = re.compile(r"clientId=([^,\]\s]+)")
_GROUP = re.compile(r"groupId=([^,\]\s]+)")


def _arg(argv, name) -> Optional[str]:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def parse_groups(out: RawOutput) -> ParseResult:
    res = ParseResult()
    command = " ".join(out.argv)
    sample_ts, sample_no, sample_raw = None, None, ""
    for n, line in content_lines(out):
        m = _SAMPLE.match(line)
        if m:
            sample_no, sample_raw = int(m.group(1)), m.group(3)
            sample_ts = normalize.parse_ts(sample_raw)
            continue
        cols = line.split()
        if cols == GROUP_COLUMNS:
            continue
        if len(cols) != len(GROUP_COLUMNS):
            res.issues.append(ParseIssue(Source.KAFKA, n, ParseIssueKind.MALFORMED, line, "unexpected column count"))
            continue
        group, topic, partition, current, end, lag, consumer_id, host, client_id = cols
        try:
            p, cur, end_i, lag_i = int(partition), int(current), int(end), int(lag)
        except ValueError:
            res.issues.append(ParseIssue(Source.KAFKA, n, ParseIssueKind.MALFORMED, line, "non-numeric offsets"))
            continue
        res.events.append(Event(
            event_id=normalize.event_id(Source.KAFKA, f"lag|{sample_ts.isoformat() if sample_ts else '-'}|{line}"),
            source=Source.KAFKA,
            level=Level.INFO,
            message=f"group {group} {topic}-{p} lag={lag_i}",
            ts_raw=sample_raw,  # verbatim from the "# sample k/N at <ts>" line; "" for an untimed snapshot
            ts_utc=sample_ts,
            app=client_id,
            component="consumer-group",
            kafka=KafkaRef(topic=topic, partition=p, offset=cur, group=group, client_id=client_id),
            attrs={"current_offset": cur, "log_end_offset": end_i, "lag": lag_i, "consumer_id": consumer_id,
                   "host": host, "sample": sample_no},
            raw_refs=[RawRecord(Source.KAFKA, command, n, line)],
        ))
    return res


def parse_offsets(out: RawOutput) -> ParseResult:
    res = ParseResult()
    for n, line in content_lines(out):
        try:
            topic, partition, offset = line.rsplit(":", 2)
            res.offsets[(topic, int(partition))] = int(offset)
        except ValueError:
            res.issues.append(ParseIssue(Source.KAFKA, n, ParseIssueKind.MALFORMED, line, "expected topic:partition:offset"))
    return res


def parse_messages(out: RawOutput) -> ParseResult:
    res = ParseResult()
    command = " ".join(out.argv)
    topic = _arg(out.argv, "--topic") or "?"
    for n, line in content_lines(out):
        if line.startswith("Processed a total of"):
            continue
        fields = line.split("\t")
        ts = partition = offset = None
        ts_raw = ""
        headers = {}
        try:
            value = json.loads(fields[-1])
            for f in fields[:-1]:
                if f.startswith("CreateTime:"):
                    ts_raw = f.split(":", 1)[1]
                    ts = normalize.parse_ts(ts_raw)
                elif f.startswith("Partition:"):
                    partition = int(f.split(":", 1)[1])
                elif f.startswith("Offset:"):
                    offset = int(f.split(":", 1)[1])
                elif f != "NO_HEADERS":
                    headers = dict(h.split(":", 1) for h in f.split(","))
        except (ValueError, IndexError) as e:
            res.issues.append(ParseIssue(Source.KAFKA, n, ParseIssueKind.MALFORMED, line, str(e)))
            continue
        if not isinstance(value, dict):
            value = {"value": value}
        identity = f"msg|{topic}|{partition}|{offset}" if partition is not None and offset is not None else f"msg|{line}"
        producer = headers.get("producer_app") or None
        res.events.append(Event(
            event_id=normalize.event_id(Source.KAFKA, identity),
            source=Source.KAFKA,
            level=Level.INFO,
            message=f"message {topic}-{partition}@{offset}",
            ts_raw=ts_raw,  # verbatim CreateTime value (epoch ms)
            ts_utc=ts,
            app=producer,  # a message belongs to the app that produced it
            component="message",
            ids=Ids(correlation_id=headers.get("correlation_id") or None),  # the PRODUCER's own ID (D25)
            keys=normalize.business_keys(value),
            kafka=KafkaRef(topic=topic, partition=partition, offset=offset, producer_app=producer),
            attrs={"headers": headers, "value": value},
            raw_refs=[RawRecord(Source.KAFKA, command, n, line)],
        ))
    return res


def parse_logs(out: RawOutput) -> ParseResult:
    res = ParseResult()
    command = " ".join(out.argv)
    topic = _arg(out.argv, "--topic")
    component = _arg(out.argv, "--component")
    tp = re.compile(rf"\b{re.escape(topic)}-(\d+)\b") if topic else None
    for n, line in content_lines(out):
        m = _LOG4J.match(line)
        lvl = normalize.level(m.group("level")) if m else None
        if not m or lvl is None:
            res.issues.append(ParseIssue(Source.KAFKA, n, ParseIssueKind.MALFORMED, line, "not a log4j line"))
            continue
        text = m.group("text")
        attrs = {"logger": m.group("logger")}
        client = _CLIENT.search(text)
        group = _GROUP.search(text)
        if client:
            attrs["client_id"] = client.group(1)
        if group:
            attrs["group"] = group.group(1)
        partitions = sorted({int(p) for p in tp.findall(text)}) if tp else []
        if partitions:
            attrs["partitions"] = partitions  # resources named in the line, for M5/M6 linking
        res.events.append(Event(
            event_id=normalize.event_id(Source.KAFKA, f"log|{component}|{line}"),
            source=Source.KAFKA,
            level=lvl,
            message=text,
            ts_raw=m.group("ts"),
            ts_utc=normalize.parse_ts(m.group("ts")),  # log4j has no zone: UTC by assumption
            component=component,
            logger=m.group("logger"),
            kafka=KafkaRef(topic=topic, partition=partitions[0] if len(partitions) == 1 else None,
                           client_id=attrs.get("client_id"), group=attrs.get("group")) if topic else None,
            attrs=attrs,
            raw_refs=[RawRecord(Source.KAFKA, command, n, line)],
        ))
    return res
