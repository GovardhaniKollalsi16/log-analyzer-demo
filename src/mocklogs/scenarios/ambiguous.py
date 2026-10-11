"""Scenario 4 (ground truth, mock side only): an ambiguous incident. The honest answer is INSUFFICIENT.

The seed is an error with no correlation ID and no business key (its class matches no
correlation-key rule), and the user isn't entitled to the seed app's config. Around it there
are scattered, unrelated symptoms: a producer retry that succeeds, a rebalance, a leader
election, a slow query. Nothing links them to the seed, so any root cause would be a guess.
"""

from __future__ import annotations

from mocklogs.scenarios.base import ScenarioKnobs
from mocklogs.scenarios.builder import COMMON_NAMES, Builder
from mocklogs.world import World

DEFAULT_NAMES = {
    "seed_app": "edge-gateway",
    "other_app": "order-service",
    "topic": "orders.events",
    **COMMON_NAMES,
}
DERIVED = {"other_group": lambda n: f"{n['other_app'].split('-')[0]}-consumers",
           "db_user": lambda n: n["other_app"].split("-")[0]}


def generate(knobs: ScenarioKnobs) -> World:
    # The seed config is always denied in this scenario; other denials (from knobs) are added on top.
    knobs_denied = ScenarioKnobs(**{**knobs.__dict__, "access_denied": knobs.access_denied | {"config:seed_app"}})
    b = Builder(knobs_denied, "ambiguous", DEFAULT_NAMES, DERIVED, ["seed_app", "other_app"])
    n = b.n
    b.topic("topic", 3, 5200)
    b.group("other_group", "topic", "other_app", "/10.0.4.11")
    b.health_noise()
    for i in range(8):
        sec = 20 + 30 * i
        oid, c = f"o-{4000 + i}", b.cid()
        b.app(sec, "INFO", "other_app", i, f"http-nio-8080-exec-{i % 5 + 1}", "orders.OrderController",
              f"Order {oid} accepted", c, keys={"order_id": oid})
        b.produce("topic", i % 3, sec + 0.1, c, "other_app", {"order_id": oid})
        b.app(sec, "INFO", "seed_app", i, f"http-nio-8443-exec-{i % 5 + 1}", "gateway.Access", "GET /v1/status -> 200")
    # scattered, unrelated symptoms
    b.client_line(95, "WARN", "other_app", 0, "producer", "topic",
                  f"[Producer clientId={b.producer_client('other_app')}] Got error produce response on topic-partition "
                  f"{n['topic']}-1, retrying (2 attempts left). Error: NOT_LEADER_OR_FOLLOWER",
                  "org.apache.kafka.clients.producer.internals.Sender", critical=True)
    b.klog(96, "INFO", "broker", "topic", f"[Partition {n['topic']}-1 broker=2] Elected as leader for partition {n['topic']}-1",
           "kafka.cluster.Partition", critical=True)
    b.klog(150, "INFO", "consumer", "topic",
           f"[Consumer clientId={b.consumer_client('other_app')}, groupId={n['other_group']}] Revoking previously assigned partitions [{n['topic']}-2]",
           "org.apache.kafka.clients.consumer.internals.ConsumerCoordinator", critical=True)
    b.db(170, 71000, "other_app", "LOG", "duration: 950.200 ms  statement: SELECT * FROM orders WHERE status = 'NEW'",
         critical=True)
    # the seed: no correlation ID, no business key
    b.app(200, "ERROR", "seed_app", 0, "http-nio-8443-exec-3", "gateway.UpstreamProxy",
          "Upstream request failed with status 502", None,
          {"type": "gateway.BadGatewayException", "message": "upstream returned 502"}, critical=True)
    seed_line = b.app_logs[-1]
    b.configs = {n["seed_app"]: {"upstream.apps": n["other_app"], "http.client.timeout.ms": "5000"}}
    return b.build(seed_line, related_roles=["other_app"], kafka_topic_roles=["topic"], kafka_group_role=None,
                   with_db=True)
