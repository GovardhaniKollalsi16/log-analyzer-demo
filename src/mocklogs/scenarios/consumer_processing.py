"""Scenario 3 (ground truth, mock side only): a poison message (D29: processing failure, lag deferred).

The upstream app publishes one order whose payload the middle app can't parse. The middle
app's consumer fails on that offset, retries it again and again (never committing), so it
never publishes the follow-up event. The downstream (seed) app times out waiting for that
event. Noise: orders on other partitions flow normally; one unrelated rebalance.
"""

from __future__ import annotations

from mocklogs.scenarios.base import ScenarioKnobs
from mocklogs.scenarios.builder import COMMON_NAMES, Builder
from mocklogs.world import World

DEFAULT_NAMES = {
    "upstream_app": "order-service",
    "middle_app": "fulfillment-worker",
    "seed_app": "notification-worker",
    "in_topic": "orders.events",
    "out_topic": "fulfillment.events",
    **COMMON_NAMES,
}
DERIVED = {
    "middle_group": lambda n: f"{n['middle_app'].split('-')[0]}-consumers",
    "seed_group": lambda n: f"{n['seed_app'].split('-')[0]}-consumers",
}
POISON_ORDER = 7
RETRIES = 5
WAIT_S = 30
CONSUMER_LOGGER = "org.apache.kafka.clients.consumer.internals.ConsumerCoordinator"


def generate(knobs: ScenarioKnobs) -> World:
    b = Builder(knobs, "consumer-processing", DEFAULT_NAMES, DERIVED, ["upstream_app", "middle_app", "seed_app"])
    n = b.n
    b.topic("in_topic", 3, 5200)
    b.topic("out_topic", 3, 7100)
    b.group("middle_group", "in_topic", "middle_app", "/10.0.3.11")
    b.group("seed_group", "out_topic", "seed_app", "/10.0.3.12")
    b.health_noise()
    b.klog(140, "INFO", "consumer", "out_topic",
           f"[Consumer clientId={b.consumer_client('seed_app')}, groupId={n['seed_group']}] Revoking previously assigned partitions [{n['out_topic']}-0]",
           CONSUMER_LOGGER)  # unrelated rebalance noise

    seed_line = None
    for i in range(10):
        sec = 20 + 25 * i
        order_id = f"o-{3000 + i}"
        up_c, mid_c, seed_c = b.cid(), b.cid(), b.cid()
        p = i % 3
        b.app(sec, "INFO", "upstream_app", i, f"http-nio-8080-exec-{i % 5 + 1}", "orders.OrderController",
              f"Order {order_id} accepted", up_c, keys={"order_id": order_id})
        poison = i == POISON_ORDER
        value = {"order_id": order_id, "status": "NEW"} if not poison else {"order_id": order_id, "status": "NEW",
                                                                            "items": "<<truncated"}
        off = b.produce("in_topic", p, sec + 0.1, up_c, "upstream_app", value)
        b.app(sec + 0.2, "INFO", "seed_app", i, f"waiter-{i % 3 + 1}", "notify.OrderEventAwaiter",
              f"Waiting for fulfillment event for order {order_id}", seed_c, keys={"order_id": order_id})
        if not poison:
            b.app(sec + 0.4, "INFO", "middle_app", i, f"consumer-{p + 1}", "fulfillment.OrderListener",
                  f"Order {order_id} processed", mid_c, keys={"order_id": order_id})
            b.produce("out_topic", p, sec + 0.5, mid_c, "middle_app", {"order_id": order_id, "status": "FULFILLED"})
            b.app(sec + 0.7, "INFO", "seed_app", i, f"waiter-{i % 3 + 1}", "notify.OrderEventAwaiter",
                  f"Fulfillment event received for order {order_id}", seed_c, keys={"order_id": order_id})
            continue
        for k in range(RETRIES):
            t = sec + 0.4 + 4 * k
            b.app(t, "ERROR", "middle_app", i, f"consumer-{p + 1}", "fulfillment.OrderListener",
                  f"Failed to process order {order_id} from {n['in_topic']}-{p} offset {off}", mid_c,
                  {"type": "com.fasterxml.jackson.core.JsonParseException", "message": "Unexpected end-of-input in field 'items'"},
                  critical=True, keys={"order_id": order_id})
            b.client_line(t + 0.01, "ERROR", "middle_app", i, "consumer", "in_topic",
                          f"[Consumer clientId={b.consumer_client('middle_app')}, groupId={n['middle_group']}] "
                          f"Exception while processing record at offset {off} on partition {n['in_topic']}-{p}; "
                          f"seeking back to offset {off} (attempt {k + 1})", CONSUMER_LOGGER)
        b.app(sec + 0.2 + WAIT_S, "ERROR", "seed_app", i, f"waiter-{i % 3 + 1}", "notify.OrderEventAwaiter",
              "Timed out waiting for fulfillment event", seed_c,
              {"type": "notify.EventTimeoutException", "message": f"no fulfillment event within {WAIT_S * 1000} ms"},
              critical=True, keys={"order_id": order_id})
        seed_line = b.app_logs[-1]

    b.configs = {
        n["seed_app"]: {
            "kafka.bootstrap.servers": n["bootstrap"],
            "kafka.consumer.topics": n["out_topic"],
            "kafka.consumer.group": n["seed_group"],
            "kafka.consumer.client.id": b.consumer_client("seed_app"),
            "upstream.apps": n["middle_app"],
            f"upstream.{n['middle_app']}.kafka.client.ids":
                f"{b.consumer_client('middle_app')},{b.producer_client('middle_app')}",
            "fulfillment.wait.timeout.ms": str(WAIT_S * 1000),
        },
    }
    return b.build(seed_line, related_roles=["middle_app"], kafka_topic_roles=["out_topic", "in_topic"],
                   kafka_group_role="seed_group", with_db=False)
