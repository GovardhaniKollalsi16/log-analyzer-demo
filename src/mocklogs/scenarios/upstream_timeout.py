"""Scenario 1 (ground truth, mock side only).

One partition of the upstream topic degrades (its ISR shrinks to the leader). The
upstream app's producer gets request timeouts on that partition, retries, then
expires the record. The seed app waits for the pricing event that never arrives and
times out. Its order is never published, so the downstream app never sees it.
Orders whose events land on healthy partitions flow normally, and some unrelated
noise (health checks, a slow cache refresh) is mixed in.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from mocklogs.scenarios.base import (
    ScenarioKnobs,
    make_rng,
    resolve_denied,
    resolve_names,
    resolve_skew,
    short_id,
)
from mocklogs.world import (
    AppLogLine,
    DbLogLine,
    Deployment,
    GroupInfo,
    Incident,
    KafkaLogLine,
    KafkaMessage,
    World,
)

DEFAULT_NAMES: Dict[str, str] = {
    "gateway_app": "edge-gateway",
    "seed_app": "order-api",
    "upstream_app": "partner-pricing",
    "downstream_app": "fulfillment-worker",
    "notify_app": "notification-worker",
    "in_topic": "pricing.events",
    "out_topic": "orders.events",
    "cluster": "cluster-a",
    "namespace": "apps",
    "bootstrap": "kafka-a:9092",
    "db_host": "db-a",
    "db_name": "appdb",
}

# Names built from other names. Derived after renames so no old name survives inside them.
DERIVED_NAMES = {
    "seed_group": lambda n: f"{n['seed_app']}-{n['in_topic'].split('.')[0]}",
    "down_group": lambda n: f"{n['downstream_app'].split('-')[0]}-consumers",
    "notify_group": lambda n: f"{n['notify_app'].split('-')[0]}-consumers",
    "db_user": lambda n: n["downstream_app"].split("-")[0],
}

ORDER_COUNT = 10
ORDER_EVERY_S = 30
FIRST_ORDER_S = 20
DEGRADED_PARTITION = 2
DEGRADED_FROM_S = 110
WAIT_TIMEOUT_S = 30
PRODUCER_RETRY_AT_S = (5, 10, 15)
DELIVERY_TIMEOUT_S = 20


def generate(knobs: ScenarioKnobs) -> World:
    n = resolve_names({**DEFAULT_NAMES, **{k: "" for k in DERIVED_NAMES}}, knobs)
    for key, derive in DERIVED_NAMES.items():
        if key not in knobs.names:
            n[key] = derive(n)
    rng = make_rng(knobs.seed, "upstream-timeout")
    t0 = knobs.t0

    def at(sec: float):
        return t0 + timedelta(seconds=sec)

    roles = ["gateway_app", "seed_app", "upstream_app", "downstream_app", "notify_app"]
    deployments = {
        n[r]: Deployment(
            app=n[r], cluster=n["cluster"], namespace=n["namespace"],
            instances=[f"{n[r]}-{short_id(rng, '', 5)}-{i}" for i in range(2)],
        )
        for r in roles
    }

    def inst(role: str, i: int) -> str:
        return deployments[n[role]].instances[i % 2]

    app_logs: List[AppLogLine] = []
    kafka_logs: List[KafkaLogLine] = []
    db_logs: List[DbLogLine] = []
    messages: List[KafkaMessage] = []

    base_offsets = {(n["in_topic"], p): 1180 + 400 * p for p in range(3)}
    base_offsets.update({(n["out_topic"], p): 5200 + 300 * p for p in range(3)})
    next_offset = dict(base_offsets)

    def app(sec, level, role, i, thread, logger, msg, corr=None, error=None, critical=False, keys=None):
        app_logs.append(AppLogLine(at(sec), level, n[role], inst(role, i), thread, logger, msg,
                                   corr, error, critical, dict(keys or {})))

    def produce(topic, partition, sec, corr, producer_role, value):
        # The header correlation_id is the PRODUCER's own ID (D25); the business keys live in the value.
        off = next_offset[(topic, partition)]
        next_offset[(topic, partition)] = off + 1
        messages.append(KafkaMessage(topic, partition, off, at(sec),
                                     {"correlation_id": corr, "producer_app": n[producer_role]}, value))

    def klog(sec, level, component, topic, text, logger, critical=False):
        kafka_logs.append(KafkaLogLine(at(sec), level, component, topic, text, logger, critical))

    # --- background noise -------------------------------------------------
    for role in roles:
        for k, sec in enumerate(range(0, 361, 60)):
            app(sec + rng.uniform(0, 2), "INFO", role, k, "health-1", "app.Health", "Health check OK")
    for role, group, topic in (("seed_app", "seed_group", "in_topic"),
                               ("downstream_app", "down_group", "out_topic"),
                               ("notify_app", "notify_group", "out_topic")):
        client = f"{n[role]}-1"
        klog(1 + rng.uniform(0, 1), "INFO", "consumer", n[topic],
             f"[Consumer clientId={client}, groupId={n[group]}] Subscribed to topic(s): {n[topic]}",
             "org.apache.kafka.clients.consumer.KafkaConsumer")
    for p in range(3):
        klog(30 + p, "INFO", "broker", n["out_topic"],
             f"[Log partition={n['out_topic']}-{p}, dir=/var/lib/kafka/data] Rolled new log segment at offset {base_offsets[(n['out_topic'], p)]}",
             "kafka.log.LocalLog")
    app(200, "WARN", "downstream_app", 0, "scheduler-1", "app.CacheRefresher",
        "Cache refresh took 1240 ms (threshold 1000 ms)")
    db_pid = 41000 + rng.randrange(1000)
    db_logs.append(DbLogLine(at(2), db_pid, n["downstream_app"], n["db_user"], n["db_name"], "LOG",
                             f"connection authorized: user={n['db_user']} database={n['db_name']}"))
    db_logs.append(DbLogLine(at(180), 100, "", "postgres", n["db_name"], "LOG", "checkpoint starting: time"))

    # --- the fault: ISR shrink on one partition of the upstream topic -------
    deg = f"{n['in_topic']}-{DEGRADED_PARTITION}"
    klog(DEGRADED_FROM_S, "WARN", "broker", n["in_topic"],
         f"[Partition {deg} broker=1] Shrinking ISR from 1,2,3 to 1. Out of sync replicas: (brokerId: 2), (brokerId: 3).",
         "kafka.cluster.Partition", critical=True)

    # --- orders ----------------------------------------------------------
    failed_orders = []
    produce_client = f"{n['upstream_app']}-producer-1"
    net_thread = f"kafka-producer-network-thread | {produce_client}"
    sender = "org.apache.kafka.clients.producer.internals.Sender"
    products = [short_id(rng, "p-", 4) for _ in range(3)]  # shared by many orders (R22)
    for i in range(ORDER_COUNT):
        sec = FIRST_ORDER_S + ORDER_EVERY_S * i
        # Each app has its own correlation ID for the same order (D25): only order_id links them.
        corr = {r: short_id(rng, "c-") for r in roles}
        order_id = f"o-{1000 + i}"
        product_id = products[i % len(products)]
        ok = {"order_id": order_id}
        p_in = i % 3
        wait_thread = f"pricing-wait-{i % 4 + 1}"
        app(sec, "INFO", "gateway_app", i, f"http-nio-8080-exec-{i % 5 + 1}", "gateway.OrderAccessLog",
            "POST /v1/orders -> 202 Accepted", corr["gateway_app"], keys=ok)
        app(sec + 0.05, "INFO", "seed_app", i, wait_thread, "orders.OrderPricingAwaiter",
            f"Order {order_id} received; awaiting pricing event", corr["seed_app"], keys=ok)
        app(sec + 0.15, "INFO", "upstream_app", i, f"pricer-{i % 3 + 1}", "pricing.PriceService",
            f"Price computed for order {order_id}", corr["upstream_app"],
            keys={"order_id": order_id, "product_id": product_id})

        if p_in == DEGRADED_PARTITION and sec >= DEGRADED_FROM_S:
            failed_orders.append(i)
            klog(sec + 5.3, "WARN", "broker", n["in_topic"],
                 f"[ReplicaManager broker=1] Produce to {deg} timed out waiting for in-sync replicas (acks=all): 1 of 3 replicas in sync",
                 "kafka.server.ReplicaManager", critical=True)
            for k, retry_s in enumerate(PRODUCER_RETRY_AT_S):
                text = (f"[Producer clientId={produce_client}] Got error produce response with correlation id "
                        f"{8800 + 10 * i + k} on topic-partition {deg}, retrying ({len(PRODUCER_RETRY_AT_S) - k - 1} attempts left). "
                        f"Error: REQUEST_TIMED_OUT")
                app(sec + 0.3 + retry_s, "WARN", "upstream_app", i, net_thread, sender, text, critical=True)
                klog(sec + 0.3 + retry_s, "WARN", "producer", n["in_topic"], text, sender, critical=True)
            expire = (f"[Producer clientId={produce_client}] Expiring 1 record(s) for {deg}:"
                      f"{DELIVERY_TIMEOUT_S * 1000} ms has passed since batch creation")
            app(sec + 0.3 + DELIVERY_TIMEOUT_S, "ERROR", "upstream_app", i, net_thread, sender, expire, critical=True)
            klog(sec + 0.3 + DELIVERY_TIMEOUT_S, "ERROR", "producer", n["in_topic"], expire, sender, critical=True)
            app(sec + 0.35 + DELIVERY_TIMEOUT_S, "ERROR", "upstream_app", i, f"pricer-{i % 3 + 1}",
                "pricing.PricePublisher", f"Failed to publish pricing event for order {order_id}", corr["upstream_app"],
                {"type": "org.apache.kafka.common.errors.TimeoutException", "message": expire.split("] ", 1)[1]},
                critical=True, keys={"order_id": order_id, "product_id": product_id})
            app(sec + 0.05 + WAIT_TIMEOUT_S, "ERROR", "seed_app", i, wait_thread, "orders.OrderPricingAwaiter",
                "Timed out waiting for pricing event", corr["seed_app"],
                {"type": "orders.PricingTimeoutException", "message": f"no pricing event within {WAIT_TIMEOUT_S * 1000} ms"},
                critical=True, keys=ok)
            app(sec + 0.06 + WAIT_TIMEOUT_S, "WARN", "seed_app", i, wait_thread, "orders.OrderPublisher",
                f"Order {order_id} not published: pricing unavailable", corr["seed_app"], critical=True, keys=ok)
            continue

        produce(n["in_topic"], p_in, sec + 0.3, corr["upstream_app"], "upstream_app",
                {"order_id": order_id, "product_id": product_id, "price": 10 + i})
        app(sec + 0.32, "INFO", "upstream_app", i, f"pricer-{i % 3 + 1}", "pricing.PricePublisher",
            f"Published pricing event for order {order_id}", corr["upstream_app"],
            keys={"order_id": order_id, "product_id": product_id})
        app(sec + 0.6, "INFO", "seed_app", i, wait_thread, "orders.OrderPricingAwaiter", "Pricing event received",
            corr["seed_app"], keys=ok)
        produce(n["out_topic"], i % 3, sec + 0.64, corr["seed_app"], "seed_app",
                {"order_id": order_id, "product_id": product_id, "status": "PRICED"})
        app(sec + 0.65, "INFO", "seed_app", i, wait_thread, "orders.OrderPublisher", f"Order {order_id} published",
            corr["seed_app"], keys=ok)
        app(sec + 0.9, "INFO", "downstream_app", i, f"consumer-{i % 2 + 1}", "fulfillment.OrderListener",
            f"Order {order_id} received", corr["downstream_app"], keys=ok)
        db_logs.append(DbLogLine(at(sec + 0.93), db_pid, n["downstream_app"], n["db_user"], n["db_name"], "LOG",
                                 f"duration: {rng.uniform(2, 6):.3f} ms  statement: INSERT INTO shipments (order_id, product_id) "
                                 f"VALUES ('{order_id}', '{product_id}')"))
        app(sec + 0.95, "INFO", "downstream_app", i, f"consumer-{i % 2 + 1}", "fulfillment.OrderListener",
            f"Order {order_id} stored", corr["downstream_app"], keys=ok)
        app(sec + 1.0, "INFO", "notify_app", i, f"consumer-{i % 2 + 1}", "notify.OrderNotifier",
            f"Notification queued for order {order_id}", corr["notify_app"], keys=ok)

    seed_order = failed_orders[-1]
    seed_line = next(l for l in app_logs if l.app == n["seed_app"] and l.level == "ERROR"
                     and l.ts == at(FIRST_ORDER_S + ORDER_EVERY_S * seed_order + 0.05 + WAIT_TIMEOUT_S))

    configs = {
        n["seed_app"]: {
            "kafka.bootstrap.servers": n["bootstrap"],
            "kafka.consumer.topics": n["in_topic"],
            "kafka.consumer.group": n["seed_group"],
            "kafka.producer.topics": n["out_topic"],
            "kafka.producer.acks": "all",
            "pricing.wait.timeout.ms": str(WAIT_TIMEOUT_S * 1000),
            "worker.threads": "4",
        },
        n["upstream_app"]: {
            "kafka.bootstrap.servers": n["bootstrap"],
            "kafka.producer.topics": n["in_topic"],
            "kafka.producer.acks": "all",
            "kafka.producer.delivery.timeout.ms": str(DELIVERY_TIMEOUT_S * 1000),
        },
        n["downstream_app"]: {
            "kafka.bootstrap.servers": n["bootstrap"],
            "kafka.consumer.topics": n["out_topic"],
            "kafka.consumer.group": n["down_group"],
            "db.host": n["db_host"],
            "db.name": n["db_name"],
            "db.pool.size": "10",
            "worker.threads": "8",
        },
    }
    groups = [
        GroupInfo(n["seed_group"], n["in_topic"], n["seed_app"], f"{n['seed_app']}-1-{short_id(rng, '', 8)}", "/10.0.1.11"),
        GroupInfo(n["down_group"], n["out_topic"], n["downstream_app"], f"{n['downstream_app']}-1-{short_id(rng, '', 8)}", "/10.0.1.12"),
        GroupInfo(n["notify_group"], n["out_topic"], n["notify_app"], f"{n['notify_app']}-1-{short_id(rng, '', 8)}", "/10.0.1.13"),
    ]

    loc = (n["cluster"], n["namespace"])
    omit = knobs.omit_inputs
    incident = Incident(
        seed_record=seed_line,
        app=None if "app" in omit else loc,
        related_apps={} if "related" in omit else {n[r]: loc for r in ("upstream_app", "downstream_app", "notify_app")},
        kafka_bootstrap=None if "kafka" in omit else n["bootstrap"],
        kafka_topics=[] if "kafka" in omit else [n["in_topic"], n["out_topic"]],
        kafka_group=None if "kafka" in omit else n["seed_group"],
    )
    world = World(
        now=seed_line.ts + timedelta(minutes=2),
        deployments=deployments,
        configs=configs,
        bootstrap=n["bootstrap"],
        topics={n["in_topic"]: 3, n["out_topic"]: 3},
        base_offsets=base_offsets,
        messages=messages,
        groups=groups,
        app_logs=app_logs,
        kafka_logs=kafka_logs,
        db_host=n["db_host"],
        db_name=n["db_name"],
        db_logs=db_logs,
        incident=incident,
        denied=resolve_denied(knobs, n),
        skew_ms=resolve_skew(knobs, n),
    )
    return world
