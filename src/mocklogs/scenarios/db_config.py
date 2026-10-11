"""Scenario 2 (ground truth, mock side only): a DB pool configured smaller than the worker threads.

The seed app's config sets `db.pool.size` far below `worker.threads`. When a burst of orders
arrives, the workers exhaust the pool, extra connections are refused by the DB ("too many
clients"), and DB calls fail. The seed is one of those failures. Noise: normal orders before
the burst, a slow-but-fine query, health checks.
"""

from __future__ import annotations

from mocklogs.scenarios.base import ScenarioKnobs
from mocklogs.scenarios.builder import COMMON_NAMES, Builder
from mocklogs.world import World

DEFAULT_NAMES = {
    "seed_app": "fulfillment-worker",
    "upstream_app": "order-service",
    "in_topic": "orders.events",
    **COMMON_NAMES,
}
DERIVED = {
    "seed_group": lambda n: f"{n['seed_app'].split('-')[0]}-consumers",
    "db_user": lambda n: n["seed_app"].split("-")[0],
}
POOL, WORKERS = 4, 16
BURST_FROM_S, BURST_ORDERS = 150, 12


def generate(knobs: ScenarioKnobs) -> World:
    b = Builder(knobs, "db-config", DEFAULT_NAMES, DERIVED, ["seed_app", "upstream_app"])
    n = b.n
    b.topic("in_topic", 3, 5200)
    b.group("seed_group", "in_topic", "seed_app", "/10.0.2.11")
    b.health_noise()
    b.klog(1, "INFO", "consumer", "in_topic",
           f"[Consumer clientId={b.consumer_client('seed_app')}, groupId={n['seed_group']}] Subscribed to topic(s): {n['in_topic']}",
           "org.apache.kafka.clients.consumer.KafkaConsumer")
    pid = 52000 + b.rng.randrange(1000)
    b.db(2, pid, "seed_app", "LOG", f"connection authorized: user={n['db_user']} database={n['db_name']}")
    b.db(95, pid, "seed_app", "LOG", "duration: 412.900 ms  statement: SELECT count(*) FROM shipments")  # slow, but fine

    seed_line = None
    orders = [(20 + 30 * i, i) for i in range(4)] + [(BURST_FROM_S + 2 * k, 4 + k) for k in range(BURST_ORDERS)]
    for sec, i in orders:
        order_id = f"o-{2000 + i}"
        up_c, seed_c = b.cid(), b.cid()
        thread = f"worker-{i % WORKERS + 1}"
        b.app(sec, "INFO", "upstream_app", i, f"http-nio-8080-exec-{i % 5 + 1}", "orders.OrderController",
              f"Order {order_id} accepted", up_c, keys={"order_id": order_id})
        b.produce("in_topic", i % 3, sec + 0.1, up_c, "upstream_app", {"order_id": order_id, "status": "NEW"})
        b.app(sec + 0.3, "INFO", "seed_app", i, thread, "fulfillment.OrderListener", f"Order {order_id} received",
              seed_c, keys={"order_id": order_id})
        in_burst = sec >= BURST_FROM_S and (i - 4) >= POOL
        if not in_burst:
            b.db(sec + 0.4, pid, "seed_app", "LOG",
                 f"duration: {b.rng.uniform(2, 6):.3f} ms  statement: INSERT INTO shipments (order_id) VALUES ('{order_id}')")
            b.app(sec + 0.5, "INFO", "seed_app", i, thread, "fulfillment.OrderStore", f"Order {order_id} stored",
                  seed_c, keys={"order_id": order_id})
            continue
        b.app(sec + 0.35, "WARN", "seed_app", i, thread, "db.ConnectionPool",
              f"Connection pool exhausted ({POOL}/{POOL} in use), waiting for a connection", seed_c,
              keys={"order_id": order_id}, critical=True)
        b.db(sec + 0.4, 60000 + i, "seed_app", "FATAL", "sorry, too many clients already", critical=True)
        b.app(sec + 0.45, "ERROR", "seed_app", i, thread, "fulfillment.OrderStore",
              f"DB call failed for order {order_id}", seed_c,
              {"type": "java.sql.SQLTransientConnectionException", "message": "could not obtain a database connection"},
              critical=True, keys={"order_id": order_id})
        seed_line = b.app_logs[-1]

    b.configs = {
        n["seed_app"]: {
            "kafka.bootstrap.servers": n["bootstrap"],
            "kafka.consumer.topics": n["in_topic"],
            "kafka.consumer.group": n["seed_group"],
            "kafka.consumer.client.id": b.consumer_client("seed_app"),
            "upstream.apps": n["upstream_app"],
            f"upstream.{n['upstream_app']}.kafka.client.ids": b.producer_client("upstream_app"),
            "db.host": n["db_host"],
            "db.name": n["db_name"],
            "db.pool.size": str(POOL),
            "worker.threads": str(WORKERS),
        },
    }
    return b.build(seed_line, related_roles=["upstream_app"], kafka_topic_roles=["in_topic"],
                   kafka_group_role="seed_group", with_db=True)
