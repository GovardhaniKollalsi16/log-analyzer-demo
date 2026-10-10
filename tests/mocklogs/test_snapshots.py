"""Golden-output snapshots of every mocklogs command shape for scenario 1 (default knobs).

The formats were reviewed by the user on 2026-10-10 ("realistic"). A diff here means a
format changed. If that's intended, regenerate with:

    UPDATE_SNAPSHOTS=1 .venv/bin/pytest tests/mocklogs/test_snapshots.py

and review the diff in git before committing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mocklogs import cli, sso
from mocklogs.render import BANNER

SNAPSHOTS = Path(__file__).parent / "snapshots"
WINDOW = ["--since-time=2026-03-14T08:54:50Z", "--until-time=2026-03-14T09:06:50Z"]
CONSOLE_PROPS = ["--property", "print.headers=true", "--property", "print.timestamp=true",
                 "--property", "print.partition=true", "--property", "print.offset=true"]

CASES = {
    # name: (argv, knobs JSON or None, logged in?)
    "incident": (["scenario", "incident"], None, True),
    "app_logs_by_business_key": (["kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps",
                                  "--timestamps", *WINDOW, "--grep", "o-1008"], None, True),
    "app_logs_thread_segment": (["kubectl", "logs", "deploy/order-service", "--context", "cluster-a", "-n", "apps",
                                 "--timestamps", *WINDOW, "--instance", "order-service-ea716-0",
                                 "--thread", "pricing-wait-1"], None, True),
    "app_logs_upstream_by_business_key": (["kubectl", "logs", "deploy/product-service", "--context", "cluster-a",
                                           "-n", "apps", "--timestamps", *WINDOW, "--grep", "o-1008"], None, True),
    "configmap": (["kubectl", "get", "configmap", "order-service-config", "--context", "cluster-a", "-n", "apps",
                   "-o", "json"], None, True),
    "consumer_group_lag_samples": (["kafka-consumer-groups", "--bootstrap-server", "kafka-a:9092", "--describe",
                                    "--group", "order-service-pricing", "--samples", "3"], None, True),
    "consumer_groups_all": (["kafka-consumer-groups", "--bootstrap-server", "kafka-a:9092", "--describe",
                             "--all-groups"], None, True),
    "get_offsets": (["kafka-get-offsets", "--bootstrap-server", "kafka-a:9092", "--topic", "pricing.events",
                     "--time", "1773478490000"], None, True),
    "console_consumer_partition": (["kafka-console-consumer", "--bootstrap-server", "kafka-a:9092", "--topic",
                                    "pricing.events", "--partition", "0", "--offset", "1180", "--max-messages", "5",
                                    *CONSOLE_PROPS], None, True),
    "console_consumer_missing_message": (["kafka-console-consumer", "--bootstrap-server", "kafka-a:9092", "--topic",
                                          "pricing.events", "--partition", "2", "--offset", "1980", "--max-messages",
                                          "50", *CONSOLE_PROPS, "--grep", "o-1008"], None, True),
    "kafka_logs_broker": (["kafka", "logs", "--bootstrap-server", "kafka-a:9092", "--component", "broker", "--topic",
                           "pricing.events", *WINDOW], None, True),
    "kafka_logs_producer": (["kafka", "logs", "--bootstrap-server", "kafka-a:9092", "--component", "producer",
                             "--topic", "pricing.events", *WINDOW], None, True),
    "kafka_logs_consumer": (["kafka", "logs", "--bootstrap-server", "kafka-a:9092", "--component", "consumer",
                             "--topic", "pricing.events", *WINDOW], None, True),
    "db_logs": (["db", "logs", "--host", "db-a", "--db", "appdb", *WINDOW], None, True),
    "refusal_sso_missing": (["kubectl", "get", "configmap", "order-service-config", "--context", "cluster-a", "-n",
                             "apps", "-o", "json"], None, False),
    "refusal_forbidden_config": (["kubectl", "get", "configmap", "order-service-config", "--context", "cluster-a",
                                  "-n", "apps", "-o", "json"], '{"access_denied": ["config:seed_app"]}', True),
    "refusal_forbidden_topic": (["kafka-get-offsets", "--bootstrap-server", "kafka-a:9092", "--topic",
                                 "pricing.events", "--time", "0"], '{"access_denied": ["kafka-topic:in_topic"]}', True),
    "refusal_forbidden_db": (["db", "logs", "--host", "db-a", "--db", "appdb"], '{"access_denied": ["db:db_name"]}', True),
    "refusal_unknown_bootstrap": (["kafka-get-offsets", "--bootstrap-server", "other:9092", "--topic",
                                   "pricing.events", "--time", "0"], None, True),
    "refusal_unknown_deployment": (["kubectl", "logs", "deploy/nope", "--context", "cluster-a", "-n", "apps"],
                                   None, True),
    "incident_inputs_omitted": (["scenario", "incident"], '{"omit_inputs": ["kafka", "related"]}', True),
}


def render_case(name, monkeypatch, tmp_path, capsys) -> str:
    argv, knobs, logged_in = CASES[name]
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", "upstream-timeout")
    if knobs:
        monkeypatch.setenv("MOCKLOGS_KNOBS", knobs)
    else:
        monkeypatch.delenv("MOCKLOGS_KNOBS", raising=False)
    if logged_in:
        sso.login()
    code = cli.main(list(argv))
    cap = capsys.readouterr()
    return f"$ mocklogs {' '.join(argv)}\n# exit={code}\n# --- stdout\n{cap.out}# --- stderr\n{cap.err}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_snapshot(name, monkeypatch, tmp_path, capsys):
    actual = render_case(name, monkeypatch, tmp_path, capsys)
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(actual)
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert actual == path.read_text(), f"{name} output changed; diff against {path}"


def test_every_snapshot_has_banner_and_no_orphans():
    names = {p.stem for p in SNAPSHOTS.glob("*.txt")}
    assert names == set(CASES), f"orphan or missing snapshots: {names ^ set(CASES)}"
    for p in SNAPSHOTS.glob("*.txt"):
        assert f"# --- stdout\n{BANNER}\n" in p.read_text(), p.name
