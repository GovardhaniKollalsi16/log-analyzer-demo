---
name: incident-logs
description: Coordinator for investigating a distributed-system incident. The incident message gives one application error line plus the inputs for each source (app cluster/namespace, Kafka cluster and topics, database host and name). Defines the rules, the "no input, no access" rule, the investigation order, and which component skill to use at each step (incident-app-logs, incident-app-config, incident-kafka, incident-db-logs). All data in this project is synthetic (MOCK).
---

# incident-logs: coordinator (v0.4)

> **v0.3 (M2).** The per-component details (logging in, required inputs, searching by time, cluster and topic, what to look for) live in **separate component skills**. This file holds the rules, the incident format, **which ID correlates across services**, the order, and which skill to use when.
> Coming next: **v1 (M5)** adds the full traversal procedure with `investigator plan`. **v2 (M10)** adds the report contract and links each component skill's allowlist. Safeguards and rate limiting will be added later by the user.
> All example names and values in these skills (`example-app`, `example-cluster`, `example.in`, …) are deliberately neutral and match no scenario. Component-skill samples are real `mocklogs` output from a neutral fixture.

## 1. Hard rules (apply to every component skill)

1. **No input, no access.** Every component skill lists its **required inputs**. If any required input is missing, **don't run any command from that skill.** Record a `missing_input` gap that names the missing input(s), and move on. Never guess, assume, or invent a cluster, namespace, topic, host, database or app name.
2. **Start from the incident.** Your first message is the incident: one application error line plus the inputs for each source (§2). Everything you fetch must trace back to it.
3. **Never parse raw logs or config yourself.** Fetch with the documented commands. `investigator` (deterministic code) parses, classifies, correlates and orders. You reason over its structured output only.
4. **Never decide chronology yourself.** Clocks across components can be skewed by up to a minute.
5. **Only run commands documented in a component skill, exactly as shown.** No pipes, redirects, `;`, `&&`, subshells or other tools.
6. **Always pass `--save-dir <workdir>`.** Output that isn't saved can't be used as evidence.
7. **You never log in.** Every component uses the **user's SSO session**. On an SSO error, stop and ask the user to run `mocklogs sso login`, then retry that command **once**. If the user declines or it still fails, record `auth_required` and continue.
8. **Refusals are findings.** Exit **4** (`Forbidden`) → record `access_denied`. Exit **5** (not found or unreachable: wrong or stale cluster, namespace, app, topic, group, host or database) → record `not_found` naming the input. In both cases don't retry, don't try other values, and continue.
9. **Don't look for or use the scenario name.** It's deliberately hidden, because it would give away the answer.
10. **A `correlation_id` only works inside one app.** Every service and sub-service has its own correlation IDs. To follow a request **across** services, use the **business key** from §3, never a correlation ID.
11. **Never infer an app from a name.** Kafka client IDs, consumer IDs, hosts and pod names are not app names. Related apps and their Kafka client IDs come **only** from the seed app's config (`upstream.apps`, `downstream.apps`, `upstream.<app>.kafka.client.ids`, `downstream.<app>.kafka.client.ids`). A client ID that the config doesn't map stays unknown.
12. **"Insufficient evidence" is a valid conclusion.** Prefer it to a guess. Missing inputs, missing access and missing auth all reduce what you may conclude; say which ones applied.

## 2. The incident message

```
INCIDENT
seed: <one application error log line>
app:    cluster=<k8s cluster> namespace=<namespace>            # where the seed app runs
app[<name>]: cluster=<k8s cluster> namespace=<namespace>       # optional, one per related app
kafka:  bootstrap=<host:port[,host:port]> topics=<topic[,topic]> [group=<consumer group>]
db:     host=<db host> name=<database>
```
- `seed` is required. Without it, there's nothing to investigate: say so and stop.
- Any other line may be absent. That source's **required inputs** are then missing, and its skill isn't run (rule 1). It isn't a failure; it gets recorded and reported.
- Values are used **exactly as written**.
- The plain `app:` line covers **only the seed app**. A related (upstream/downstream) app is fetched only if the incident has an `app[<name>]:` line for it.
- **Where vs. who:** the incident is the only source of **where** to look (clusters, namespaces, Kafka bootstrap and topics, DB host and name). The seed app's config only says **who** is related (upstream/downstream apps and their Kafka client IDs). Never use a cluster, topic or DB from the config to access anything; if it differs from the incident, report the mismatch.

## 3. Which ID correlates across services

| ID | Scope | Use it to |
|---|---|---|
| `correlation_id` | **One app only.** Every service and sub-service has its own | Search **that app's** logs (`incident-app-logs`). A Kafka header `correlation_id` is the **producer's** own ID, so use it only to search the producer app's logs |
| business key (below) | **Across services:** app logs, Kafka messages, DB logs | Find the same order/product in other apps, in Kafka messages and in DB statements |

**Choosing the business key (by API).** Look at the seed record's source class: the last segment of its `logger` (e.g. `example.OrderHandler` → `OrderHandler`). The first rule whose prefix matches picks the key. The key's value is the seed record's field with that name. `investigator` applies this table deterministically; you don't pick the key by judgment.

```json
{"correlation_keys": [
  {"source_class_prefix": "Order",   "key": "order_id",   "stored_as": {"app_logs": "order_id",   "kafka": "order_id",   "db": "order_id"}},
  {"source_class_prefix": "Product", "key": "product_id", "stored_as": {"app_logs": "product_id", "kafka": "product_id", "db": "product_id"}}
]}
```
*More API → key rules will be added by the user.*

**Where the keys come from:** orders come from the **OrderService** and product-based inputs from the **ProductService**. Each logs its business key (`order_id` / `product_id`) together with **its own** `correlation_id`. Inside one service, every line for the same order or product shares that correlation ID, so search by the business key first, then by the correlation ID you find.
- **No rule matches, or the seed record lacks that field** → there's no business key. Every cross-service step (Kafka messages, related apps, DB) is recorded as `missing_input: business key`. In-app steps still run.
- A business key isn't unique to one request: a product appears in many orders. Matches only count inside the incident time window, and `investigator` treats them as weaker than an in-app `correlation_id` match.

## 4. Which skill, in which order

| Step | What | Skill | Required inputs (all must be present, or the step is skipped) |
|---|---|---|---|
| 1 | The seed app's logs: its `correlation_id` + the seed's thread on its instance | `incident-app-logs` | `app.cluster`, `app.namespace`, plus `app`, `ts` (and `correlation_id` if present) from the seed line |
| 2 | The seed app's config (seed app **only**) | `incident-app-config` | `app.cluster`, `app.namespace`, plus `app` from the seed line |
| 3 | Kafka: lag; messages carrying the **business key**; broker/client logs | `incident-kafka` | `kafka.bootstrap`, `kafka.topics` (plus `kafka.group` for lag, and the business key for message search) |
| 4 | **One hop upstream and one hop downstream:** the apps the seed app's config declares in `upstream.apps` / `downstream.apps`. Search their app logs by the **business key**, then by **their own** `correlation_id` and thread from what that search returns | `incident-app-logs` | The seed app's config (for the app list), the business key, and that app's `app[<name>]:` line from the incident. No config → no related apps (`missing_input: upstream/downstream apps`). No `app[<name>]:` line → skip that app (`missing_input`). Never reuse the seed's cluster |
| 5 | The database: statements carrying the **business key** | `incident-db-logs` | `db.host`, `db.name` (and the business key) |

**Time window:** derived from the seed line's `ts`. By default, from 10 minutes before to 2 minutes after; widen once if a step finds nothing. (Defaults to be tuned; `investigator plan` will compute them in v1.)

## 5. What counts as an error

You don't classify records. `investigator` labels every record **ERROR / SYMPTOM / CONTEXT / ANOMALY** with an `error_code`, per component (definitions: `docs/design/PROPOSAL.md` §2). Each component skill's "What to look for" section only helps you pick filters and notice when a step needs widening.
