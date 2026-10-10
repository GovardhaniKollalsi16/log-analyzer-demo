---
name: incident-app-config
description: How to fetch an application's config for an incident investigation (kubectl get configmap shape) - logging in via the user's SSO, picking the cluster/namespace, and what to read from it (Kafka bootstrap servers, topics, consumer group, database, timeouts/retries/pool sizes). Used by the incident-logs coordinator for step 2, seed app only. All data is synthetic (MOCK).
---

# incident-app-config (v0)

> Part of the `incident-logs` investigation. Read that coordinator's hard rules first; they apply here.
> Example values are deliberately neutral and match no scenario. Output samples are illustrative until `mocklogs` exists.

## 1. Logging in

- Config is read with the **user's SSO session**. **You never run `mocklogs sso login`.**
- SSO missing or expired (exit code **3**): stop, ask the user to run `mocklogs sso login`, and retry **once**. If the user declines → record `auth_required`.
- Not entitled (exit code **4**):
  ```
  # MOCK DATA — synthetic, not from any real system
  Error from server (Forbidden): configmaps "example-app-config" is forbidden: user cannot get resource in namespace "apps" on cluster "example-cluster"
  ```
  Record `access_denied`. **This matters:** without the config, you can't find the app's topics or database, so the Kafka and DB steps can't be planned, and the confidence you may claim drops. Say so explicitly in the report.

## 2. Where the inputs come from

| Input | Source |
|---|---|
| `cluster`, `namespace`, `app` | The seed line |

Fetch config for the **seed app only**. Never fetch config for upstream or downstream apps.

## 3. Command
```
mocklogs kubectl get configmap <app>-config --context <cluster> -n <namespace> -o json --save-dir <workdir>
```
Config has no time dimension: it's the current config. There is no change history, so don't reason about *when* a value changed.

## 4. Output format (illustrative)
```
# MOCK DATA — synthetic, not from any real system
{"apiVersion":"v1","kind":"ConfigMap",
 "metadata":{"name":"example-app-config","namespace":"apps","annotations":{"cluster":"example-cluster"}},
 "data":{
   "kafka.bootstrap.servers":"example-kafka:9092",
   "kafka.consumer.topics":"example.in",
   "kafka.consumer.group":"example-app-group",
   "kafka.producer.topics":"example.out",
   "db.host":"example-db-host",
   "db.name":"example-db",
   "http.client.timeout.ms":"5000",
   "kafka.producer.retries":"3",
   "db.pool.size":"10",
   "worker.threads":"8"}}
```

## 5. What to read from it

These keys are what the next steps need:

| Key | Used for |
|---|---|
| `kafka.bootstrap.servers` | The Kafka **cluster** for every `incident-kafka` command |
| `kafka.consumer.topics` + `kafka.consumer.group` | Topics the app **consumes** → where to find **upstream** producers; the group to check for lag |
| `kafka.producer.topics` | Topics the app **produces** → where to find **downstream** consumers |
| `db.host` + `db.name` | Whether there's a downstream DB, and where (`incident-db-logs`). Empty or absent → no DB step |
| timeouts, retries, pool sizes, thread counts | Limits that `investigator` checks for inconsistencies (e.g. pool size below worker threads, retries × timeout longer than a consumer can wait). You don't judge these yourself |

Missing keys aren't errors on your part. Record that the step couldn't be planned (e.g. "no consumed topics in config") and move on.
