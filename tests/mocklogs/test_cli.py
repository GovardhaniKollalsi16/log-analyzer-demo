"""Behavior of the mock CLI (M2). Format snapshots come after the user reviews samples."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from mocklogs import cli, sso
from mocklogs.render import BANNER
from mocklogs.scenarios import load
from mocklogs.scenarios.base import DEFAULT_T0, ScenarioKnobs

SCENARIO = "upstream-timeout"
WINDOW = ["--since-time=2026-03-14T08:54:50Z", "--until-time=2026-03-14T09:06:50Z"]

FETCH_COMMANDS = {
    "app_logs": ["kubectl", "logs", "deploy/order-api", "--context", "cluster-a", "-n", "apps", "--timestamps", *WINDOW],
    "config": ["kubectl", "get", "configmap", "order-api-config", "--context", "cluster-a", "-n", "apps", "-o", "json"],
    "lag": ["kafka-consumer-groups", "--bootstrap-server", "kafka-a:9092", "--describe", "--group", "order-api-pricing", "--samples", "3"],
    "all_groups": ["kafka-consumer-groups", "--bootstrap-server", "kafka-a:9092", "--describe", "--all-groups"],
    "offsets": ["kafka-get-offsets", "--bootstrap-server", "kafka-a:9092", "--topic", "pricing.events", "--time", "0"],
    "messages": ["kafka-console-consumer", "--bootstrap-server", "kafka-a:9092", "--topic", "pricing.events",
                 "--from-beginning", "--property", "print.headers=true"],
    "kafka_logs": ["kafka", "logs", "--bootstrap-server", "kafka-a:9092", "--component", "broker", "--topic", "pricing.events", *WINDOW],
    "db_logs": ["db", "logs", "--host", "db-a", "--db", "appdb", *WINDOW],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", SCENARIO)
    monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    return tmp_path


@pytest.fixture
def logged_in(env):
    sso.login()
    return env


def run(argv, capsys):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- scenario / SSO gating -------------------------------------------------------

def test_no_scenario_loaded(env, monkeypatch, capsys):
    monkeypatch.delenv("MOCKLOGS_SCENARIO")
    sso.login()
    code, out, err = run(FETCH_COMMANDS["config"], capsys)
    assert code == cli.NO_SCENARIO and "no MOCK scenario loaded" in err


@pytest.mark.parametrize("name", sorted(FETCH_COMMANDS))
def test_every_fetch_requires_sso(env, capsys, name):
    code, out, err = run(FETCH_COMMANDS[name], capsys)
    assert code == cli.AUTH
    assert out.startswith(BANNER)
    assert "Ask the user to run: mocklogs sso login" in err


def test_expired_session_is_refused(env, capsys):
    sso.login(ttl_minutes=-1)
    code, _, _ = run(FETCH_COMMANDS["config"], capsys)
    assert code == cli.AUTH


@pytest.mark.parametrize("name", sorted(FETCH_COMMANDS))
def test_every_fetch_works_when_logged_in_and_starts_with_banner(logged_in, capsys, name):
    code, out, err = run(FETCH_COMMANDS[name], capsys)
    assert code == cli.OK, err
    assert out.splitlines()[0] == BANNER
    assert len(out.splitlines()) > 1


def test_session_marker_and_scenario_name_never_leak(logged_in, capsys):
    marker = sso.session_marker_for_tests()
    assert marker and marker.startswith("MOCK-SESSION-")
    save = logged_in / "work"
    texts = []
    for argv in [["sso", "status"], ["sso", "login"], ["scenario", "incident"]] + list(FETCH_COMMANDS.values()):
        code, out, err = run(list(argv) + (["--save-dir", str(save)] if argv[0] not in ("sso", "scenario") else []), capsys)
        texts += [out, err]
        marker = sso.session_marker_for_tests()  # login rotates it
        assert marker not in out + err
    texts += [p.read_text() for p in (save / "raw").iterdir()]
    blob = "\n".join(texts)
    assert sso.session_marker_for_tests() not in blob
    assert SCENARIO not in blob


# --- refusals -------------------------------------------------------------------

@pytest.mark.parametrize("denied,name,needle", [
    ("logs:seed_app", "app_logs", "Forbidden"),
    ("config:seed_app", "config", "Forbidden"),
    ("kafka-group:seed_group", "lag", "GroupAuthorizationException"),
    ("kafka-topic:in_topic", "offsets", "TopicAuthorizationException"),
    ("kafka-topic:in_topic", "messages", "TopicAuthorizationException"),
    ("db:db_name", "db_logs", "permission denied"),
])
def test_access_denied(logged_in, monkeypatch, capsys, denied, name, needle):
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"access_denied": [denied]}))
    code, out, err = run(FETCH_COMMANDS[name], capsys)
    assert code == cli.FORBIDDEN and needle in err and out.startswith(BANNER)


@pytest.mark.parametrize("argv", [
    ["kubectl", "logs", "deploy/order-api", "--context", "nope", "-n", "apps"],
    ["kubectl", "logs", "deploy/nope", "--context", "cluster-a", "-n", "apps"],
    ["kubectl", "get", "configmap", "nope-config", "--context", "cluster-a", "-n", "apps", "-o", "json"],
    ["kafka-get-offsets", "--bootstrap-server", "other:9092", "--topic", "pricing.events", "--time", "0"],
    ["kafka-get-offsets", "--bootstrap-server", "kafka-a:9092", "--topic", "nope", "--time", "0"],
    ["kafka-consumer-groups", "--bootstrap-server", "kafka-a:9092", "--describe", "--group", "nope"],
    ["db", "logs", "--host", "nope", "--db", "appdb"],
    ["db", "logs", "--host", "db-a", "--db", "nope"],
])
def test_wrong_inputs_are_not_found(logged_in, capsys, argv):
    code, _, _ = run(argv, capsys)
    assert code == cli.NOT_FOUND


def test_instance_and_thread_must_come_together(logged_in, capsys):
    code, _, err = run(FETCH_COMMANDS["app_logs"] + ["--thread", "x"], capsys)
    assert code == cli.USAGE and "together" in err


# --- --save-dir ------------------------------------------------------------------

def test_save_dir_writes_numbered_output_and_meta_including_refusals(env, capsys):
    save = env / "work"
    run(FETCH_COMMANDS["config"] + ["--save-dir", str(save)], capsys)  # refused: no SSO yet
    sso.login()
    run(FETCH_COMMANDS["config"] + ["--save-dir", str(save)], capsys)
    files = sorted((save / "raw").glob("*.txt"))
    assert [f.name[:4] for f in files] == ["001-", "002-"]
    metas = [json.loads(f.with_suffix(".meta.json").read_text()) for f in files]
    assert [m["exit_code"] for m in metas] == [cli.AUTH, cli.OK]
    assert metas[1]["argv"][:3] == ["mocklogs", "kubectl", "get"]
    assert files[1].read_text().startswith(BANNER + "\n{")


# --- scenario content and knobs ------------------------------------------------

def test_incident_has_required_inputs_and_parseable_seed(logged_in, capsys):
    code, out, _ = run(["scenario", "incident"], capsys)
    lines = out.splitlines()
    assert lines[:2] == [BANNER, "INCIDENT"]
    seed = json.loads(lines[2][len("seed: "):])
    assert seed["level"] == "ERROR" and seed["app"] == "order-api" and seed["correlation_id"]
    assert seed["order_id"] and seed["logger"].rsplit(".", 1)[-1].startswith("Order")
    assert any(l.startswith("kafka:  bootstrap=kafka-a:9092 topics=") for l in lines)
    assert any(l.startswith("app[partner-pricing]:") for l in lines)
    assert not any(l.startswith("db:") for l in lines)  # the seed app has no database


def test_omit_inputs_knob(logged_in, monkeypatch, capsys):
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"omit_inputs": ["kafka", "related"]}))
    _, out, _ = run(["scenario", "incident"], capsys)
    assert "kafka:" not in out and "app[" not in out and "app:    cluster=" in out


def test_same_seed_same_world_different_seed_different_ids():
    a, b, c = load(SCENARIO), load(SCENARIO), load(SCENARIO, ScenarioKnobs(seed=99))
    ids = lambda w: [l.correlation_id for l in w.app_logs if l.correlation_id]  # noqa: E731
    assert ids(a) == ids(b)
    assert ids(a) != ids(c)


def test_rename_knob_removes_every_default_name(logged_in, monkeypatch, capsys):
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"names": {
        "seed_app": "svc-q", "upstream_app": "svc-u", "in_topic": "t.in", "cluster": "c-9"}}))
    _, out, _ = run(["scenario", "incident"], capsys)
    for old in ("order-api", "partner-pricing", "pricing.events", "cluster-a"):
        assert old not in out
    assert '"app":"svc-q"' in out and "t.in" in out and "app[svc-u]" in out


def test_t0_knob_shifts_every_timestamp():
    base = load(SCENARIO)
    shifted = load(SCENARIO, ScenarioKnobs(t0=DEFAULT_T0 + timedelta(days=3)))
    assert [l.ts + timedelta(days=3) for l in base.app_logs] == [l.ts for l in shifted.app_logs]


def test_skew_knob_shifts_rendered_kafka_times(logged_in, monkeypatch, capsys):
    _, before, _ = run(FETCH_COMMANDS["kafka_logs"], capsys)
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"skew_ms": {"kafka": 45000}}))
    _, after, _ = run(FETCH_COMMANDS["kafka_logs"], capsys)
    assert "[2026-03-14 09:01:50,000]" in before and "[2026-03-14 09:02:35,000]" in after


def test_drop_and_malform_only_touch_non_critical_lines(logged_in, monkeypatch, capsys):
    world = load(SCENARIO)
    critical_msgs = [l.msg for l in world.app_logs if l.app == "partner-pricing" and l.critical]
    argv = ["kubectl", "logs", "deploy/partner-pricing", "--context", "cluster-a", "-n", "apps", "--timestamps"]
    _, clean, _ = run(argv, capsys)
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"drop_rate": 0.5, "malformed_rate": 0.4}))
    _, noisy, _ = run(argv, capsys)
    assert len(noisy.splitlines()) < len(clean.splitlines())
    for msg in critical_msgs:
        assert msg in noisy
    assert any(not l.rstrip().endswith("}") for l in noisy.splitlines()[1:])  # some lines truncated


def test_shuffle_and_dup_knobs(logged_in, monkeypatch, capsys):
    _, clean, _ = run(FETCH_COMMANDS["app_logs"], capsys)
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"shuffle": True, "dup_rate": 0.3}))
    _, noisy, _ = run(FETCH_COMMANDS["app_logs"], capsys)
    c, n = clean.splitlines()[1:], noisy.splitlines()[1:]
    assert sorted(set(c)) == sorted(set(n))  # same lines...
    assert len(n) > len(c) and n != c        # ...duplicated and reordered


def test_ground_truth_shape():
    """Sanity check of the injected fault. Lives in tests, never in investigator."""
    w = load(SCENARIO)
    seed = w.incident.seed_record
    assert seed.app == "order-api" and seed.level == "ERROR"
    order_id = seed.keys["order_id"]
    assert not [m for m in w.messages if m.value.get("order_id") == order_id]  # pricing never arrived
    upstream_errors = [l for l in w.app_logs if l.app == "partner-pricing" and l.level == "ERROR"
                       and l.keys.get("order_id") == order_id]
    assert upstream_errors and upstream_errors[0].correlation_id != seed.correlation_id
    assert any("Shrinking ISR" in l.text for l in w.kafka_logs)


# --- correlation keys (D25) --------------------------------------------------------

def test_seed_comes_from_an_order_class_and_carries_order_id():
    seed = load(SCENARIO).incident.seed_record
    assert seed.logger.rsplit(".", 1)[-1].startswith("Order")
    assert seed.keys.get("order_id")


def test_correlation_ids_are_per_app_and_business_keys_link_across_apps():
    w = load(SCENARIO)
    by_order = {}
    for l in w.app_logs:
        if "order_id" in l.keys:
            by_order.setdefault(l.keys["order_id"], {}).setdefault(l.app, set()).add(l.correlation_id)
    for order_id, apps in by_order.items():
        assert all(len(ids) == 1 for ids in apps.values()), order_id       # one ID per app per order
        flat = [next(iter(ids)) for ids in apps.values()]
        assert len(set(flat)) == len(flat), order_id                       # never shared across apps


def test_kafka_header_correlation_id_is_the_producers_own():
    w = load(SCENARIO)
    for m in w.messages:
        producer = m.headers["producer_app"]
        producer_ids = {l.correlation_id for l in w.app_logs
                        if l.app == producer and l.keys.get("order_id") == m.value["order_id"]}
        assert m.headers["correlation_id"] in producer_ids
        assert "order_id" in m.value and "product_id" in m.value


def test_product_ids_are_shared_across_orders():
    w = load(SCENARIO)
    products = [m.value["product_id"] for m in w.messages if m.topic == "pricing.events"]
    assert len(set(products)) < len(products)  # R22: a business key isn't request-unique


def test_db_statements_carry_business_keys(logged_in, capsys):
    order_id = load(SCENARIO).incident.seed_record.keys["order_id"]
    _, out, _ = run(["db", "logs", "--host", "db-a", "--db", "appdb", "--grep", "o-1000"], capsys)
    assert "order_id" in out and "'o-1000'" in out
    _, out, _ = run(["db", "logs", "--host", "db-a", "--db", "appdb", "--grep", order_id], capsys)
    assert out.splitlines() == [BANNER]  # the failed order never reached the DB
