"""M3 unit tests on hand-written inputs (no scenario data)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from investigator import normalize
from investigator.adapters.base import RawOutput
from investigator.correlation_keys import KeyRule, choose_business_key, load_rules
from investigator.dedupe import dedupe
from investigator.models import GapReason, Level, ParseIssueKind, Source
from investigator.parsing import dispatch
from investigator.parsing.incident import IncidentError, parse_incident

UTC = timezone.utc
BANNER = "# MOCK DATA — synthetic, not from any real system"
SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "incident-logs" / "SKILL.md"


def out(argv, lines, code=0, name="001-x"):
    return RawOutput(name=name, argv=["tool"] + argv, exit_code=code, lines=[BANNER] + lines)


# --- timestamps & levels -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("2026-01-01T00:00:01.250Z", datetime(2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC)),
    ("2026-01-01T00:00:01.250000000Z", datetime(2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC)),   # kubectl nanos
    ("2026-01-01T02:00:01.5+02:00", datetime(2026, 1, 1, 0, 0, 1, 500000, tzinfo=UTC)),      # offset zone
    ("2025-12-31T19:00:01-05:00", datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)),                # no fraction
    ("2026-01-01 00:00:01,250", datetime(2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC)),          # log4j, no zone
    ("2026-01-01 00:00:01.250 UTC", datetime(2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC)),      # postgres
    ("1767225601250", datetime(2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC)),                    # epoch ms
])
def test_parse_ts_shapes(raw, expected):
    assert normalize.parse_ts(raw) == expected


@pytest.mark.parametrize("raw", ["", "yesterday", "2026-13-01T00:00:00Z", "12:00"])
def test_parse_ts_rejects_garbage(raw):
    assert normalize.parse_ts(raw) is None


def test_levels_unified():
    assert normalize.level("WARNING") is Level.WARN and normalize.level("LOG") is Level.INFO
    assert normalize.level("PANIC") is Level.CRITICAL and normalize.level("nope") is None


def test_business_keys_only_from_structured_id_fields():
    assert normalize.business_keys({"order_id": "o-1", "correlation_id": "c-1", "msg": "order_id o-2",
                                    "product_id": "p-1", "empty_id": ""}) == {"order_id": "o-1", "product_id": "p-1"}


# --- app logs ----------------------------------------------------------------------

APP_LINE = ('2026-01-01T00:00:01.250000000Z {"ts":"2026-01-01T00:00:01.250Z","level":"ERROR","cluster":"c-1",'
            '"namespace":"ns","app":"app-x","instance":"app-x-0","thread":"w-1","logger":"x.OrderThing",'
            '"correlation_id":"c-9","order_id":"o-1","msg":"boom","error":{"type":"E","message":"m"}}')


def test_app_log_line_parses_everything():
    res = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x"], [APP_LINE]))
    (ev,) = res.events
    assert ev.source is Source.APP and ev.level is Level.ERROR and ev.app == "app-x"
    assert (ev.cluster, ev.namespace, ev.instance, ev.thread) == ("c-1", "ns", "app-x-0", "w-1")
    assert ev.ids.correlation_id == "c-9" and ev.keys == {"order_id": "o-1"}
    assert ev.ts_utc == datetime(2026, 1, 1, 0, 0, 1, 250000, tzinfo=UTC)
    assert ev.attrs["error"]["type"] == "E" and ev.raw_refs[0].line_no == 2


def test_app_log_malformed_and_missing_fields_are_issues_not_crashes():
    lines = [APP_LINE[:80], '{"ts":"2026-01-01T00:00:00Z","level":"INFO"}', "not json", APP_LINE]
    res = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x"], lines))
    assert len(res.events) == 1
    assert [i.kind for i in res.issues] == [ParseIssueKind.MALFORMED, ParseIssueKind.MISSING_FIELD,
                                            ParseIssueKind.MALFORMED]


def test_same_record_with_and_without_kubectl_prefix_has_same_id():
    body = APP_LINE.split(" ", 1)[1]
    a = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x"], [APP_LINE])).events[0]
    b = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x"], [body])).events[0]
    assert a.event_id == b.event_id


# --- Kafka -------------------------------------------------------------------------

def test_kafka_log_internal_correlation_id_is_not_an_application_id():
    line = ("[2026-01-01 00:00:05,300] WARN [Producer clientId=app-y-producer-1] Got error produce response with "
            "correlation id 8812 on topic-partition t-1-2, retrying (2 attempts left). Error: REQUEST_TIMED_OUT "
            "(org.apache.kafka.clients.producer.internals.Sender)")
    res = dispatch.parse_output(out(["kafka", "logs", "--component", "producer", "--topic", "t-1"], [line]))
    (ev,) = res.events
    assert ev.ids.is_empty() and ev.keys == {}
    assert ev.attrs["client_id"] == "app-y-producer-1" and ev.attrs["partitions"] == [2]
    assert ev.level is Level.WARN and ev.ts_utc == datetime(2026, 1, 1, 0, 0, 5, 300000, tzinfo=UTC)


def test_console_message_header_id_belongs_to_producer_and_keys_come_from_value():
    line = 'CreateTime:1767225600000\tPartition:1\tOffset:42\tcorrelation_id:c-7,producer_app:app-y\t{"order_id":"o-1","product_id":"p-1"}'
    res = dispatch.parse_output(out(["kafka-console-consumer", "--topic", "t-1"], [line, "Processed a total of 1 messages"]))
    (ev,) = res.events
    assert ev.app == "app-y" and ev.ids.correlation_id == "c-7"
    assert ev.keys == {"order_id": "o-1", "product_id": "p-1"}
    assert (ev.kafka.topic, ev.kafka.partition, ev.kafka.offset) == ("t-1", 1, 42)


def test_message_identity_is_topic_partition_offset_not_print_options():
    a = 'CreateTime:1767225600000\tPartition:1\tOffset:42\tcorrelation_id:c-7,producer_app:app-y\t{"order_id":"o-1"}'
    b = 'Partition:1\tOffset:42\t{"order_id":"o-1"}'
    ea = dispatch.parse_output(out(["kafka-console-consumer", "--topic", "t-1"], [a])).events[0]
    eb = dispatch.parse_output(out(["kafka-console-consumer", "--topic", "t-1"], [b])).events[0]
    assert ea.event_id == eb.event_id


def test_consumer_group_samples_become_lag_events_with_sample_time():
    lines = ["# sample 1/2 at 2026-01-01T00:05:00.000Z", "",
             "GROUP  TOPIC  PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID  HOST  CLIENT-ID",
             "g-1  t-1  0  10  15  5  cons-1  /10.0.0.1  app-x",
             "# sample 2/2 at 2026-01-01T00:06:00.000Z", "",
             "GROUP  TOPIC  PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID  HOST  CLIENT-ID",
             "g-1  t-1  0  10  25  15  cons-1  /10.0.0.1  app-x"]
    res = dispatch.parse_output(out(["kafka-consumer-groups", "--describe", "--group", "g-1"], lines))
    assert [e.attrs["lag"] for e in res.events] == [5, 15]
    assert [e.ts_utc.minute for e in res.events] == [5, 6]
    assert len({e.event_id for e in res.events}) == 2  # same row text, different sample time


def test_offsets_parse():
    res = dispatch.parse_output(out(["kafka-get-offsets", "--topic", "t-1"], ["t-1:0:100", "t-1:1:7", "junk"]))
    assert res.offsets == {("t-1", 0): 100, ("t-1", 1): 7} and len(res.issues) == 1


# --- DB ------------------------------------------------------------------------------

def test_db_statement_columns_become_business_keys():
    line = ("2026-01-01 00:00:20.930 UTC [41] app=app-z user=u db=d LOG:  duration: 3.2 ms  statement: "
            "INSERT INTO t (order_id, product_id, qty) VALUES ('o-1', 'p-1', '3')")
    where = "2026-01-01 00:00:21.000 UTC [41] app=app-z user=u db=d ERROR:  canceling statement: UPDATE t SET x=1 WHERE order_id = 'o-2'"
    res = dispatch.parse_output(out(["db", "logs", "--host", "h", "--db", "d"], [line, where]))
    assert res.events[0].keys == {"order_id": "o-1", "product_id": "p-1"}
    assert res.events[1].keys == {"order_id": "o-2"} and res.events[1].level is Level.ERROR


# --- config ----------------------------------------------------------------------------

def test_configmap_becomes_entries_and_citable_events():
    lines = ['{"metadata":{"name":"app-x-config","namespace":"ns","annotations":{"cluster":"c-1"}},',
             '"data":{"kafka.consumer.topics":"t-1","db.pool.size":"10"}}']
    res = dispatch.parse_output(out(["kubectl", "get", "configmap", "app-x-config"], lines))
    assert {(c.app, c.key, c.value) for c in res.config} == {("app-x", "kafka.consumer.topics", "t-1"),
                                                            ("app-x", "db.pool.size", "10")}
    assert all(e.source is Source.APP_CONFIG and e.ts_utc is None for e in res.events)


# --- refusals ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,reason", [(3, GapReason.AUTH_REQUIRED), (4, GapReason.ACCESS_DENIED),
                                         (5, GapReason.NOT_FOUND)])
def test_refusals_become_coverage_gaps(code, reason):
    res = dispatch.parse_output(out(["kubectl", "get", "configmap", "app-x-config"], ["error: refused"], code=code))
    (gap,) = res.gaps
    assert gap.reason is reason and gap.component is Source.APP_CONFIG and gap.target == "app-x-config"
    assert gap.detail == "error: refused" and not res.events


def test_unknown_command_shape_is_an_issue():
    res = dispatch.parse_output(out(["something", "else"], ["x"]))
    assert res.issues[0].kind is ParseIssueKind.UNKNOWN_FORMAT


# --- dedupe --------------------------------------------------------------------------

def test_dedupe_overlap_vs_true_duplicates():
    a = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x", "--grep", "o-1"], [APP_LINE, APP_LINE])).events
    b = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x", "--grep", "c-9"], [APP_LINE])).events
    rerun = dispatch.parse_output(out(["kubectl", "logs", "deploy/app-x", "--grep", "c-9"], [APP_LINE])).events
    (ev,) = dedupe(a + b + rerun)
    assert ev.duplicate_count == 2          # repeated inside one output
    assert len(ev.raw_refs) == 3            # 2 lines in the first output + 1 in the second; the rerun adds nothing new


# --- incident & correlation keys --------------------------------------------------------

SEED = APP_LINE.split(" ", 1)[1]


def test_correlation_rules_load_from_the_coordinator_skill():
    rules = load_rules(SKILL)
    assert [(r.source_class_prefix, r.key) for r in rules] == [("Order", "order_id"), ("Product", "product_id")]


@pytest.mark.parametrize("logger,keys,expected", [
    ("x.OrderThing", {"order_id": "o-1"}, "order_id"),
    ("x.ProductThing", {"product_id": "p-1", "order_id": "o-1"}, "product_id"),
    ("x.OrderThing", {"product_id": "p-1"}, None),   # rule matches but the seed lacks that field
    ("x.Other", {"order_id": "o-1"}, None),          # no rule matches
    (None, {"order_id": "o-1"}, None),
])
def test_choose_business_key(logger, keys, expected):
    rules = [KeyRule("Order", "order_id", {}), KeyRule("Product", "product_id", {})]
    assert choose_business_key(logger, keys, rules) == expected


def test_parse_full_incident():
    text = "\n".join([BANNER, "INCIDENT", f"seed: {SEED}", "app:    cluster=c-1 namespace=ns",
                      "app[app-y]: cluster=c-2 namespace=ns2", "kafka:  bootstrap=k:9092 topics=t-1,t-2 group=g-1",
                      "db:     host=h name=d"])
    inc = parse_incident(text, load_rules(SKILL))
    assert inc.seed.app == "app-x" and inc.seed.business_key == "order_id" and inc.seed.keys["order_id"] == "o-1"
    assert inc.app.cluster == "c-1" and inc.related_apps["app-y"].namespace == "ns2"
    assert inc.kafka_bootstrap == "k:9092" and inc.kafka_topics == ["t-1", "t-2"] and inc.kafka_group == "g-1"
    assert (inc.db_host, inc.db_name) == ("h", "d")
    assert inc.seed_event.event_id == inc.seed.event_id


def test_incident_absent_or_partial_lines_mean_no_input():
    inc = parse_incident(f"INCIDENT\nseed: {SEED}\nkafka: topics=t-1\ndb: host=h\napp: cluster=c-1")
    assert inc.app is None and inc.kafka_bootstrap is None and inc.kafka_topics == []
    assert inc.db_host is None and inc.db_name is None and inc.seed.business_key is None  # no rules given


@pytest.mark.parametrize("text,msg", [("INCIDENT\napp: cluster=c namespace=n", "no seed"),
                                      ("INCIDENT\nseed: {not json", "not a valid app log record")])
def test_incident_without_valid_seed_is_rejected(text, msg):
    with pytest.raises(IncidentError, match=msg):
        parse_incident(text)
