---
name: incident-app-config
description: How to fetch the seed application's config for an incident investigation (kubectl get configmap shape) - logging in via the user's SSO, the required inputs (cluster, namespace, app from the incident), and what the config is used for (which topics the app consumes vs produces, its consumer group, and limits such as timeouts/retries/pool sizes). Used by the incident-logs coordinator for step 2, seed app only. All data is synthetic (MOCK).
---

# incident-app-config (v0.1)

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
  Record `access_denied`. **This matters:** without the config, you can't tell which incident topics the app consumes vs. produces, and you can't check its limits. That lowers the confidence you may claim. Say so explicitly in the report. (Kafka and DB access don't depend on it: their inputs come from the incident.)

## 2. Required inputs

| Input | Required? | Where it must come from |
|---|---|---|
| `cluster` | **Required** | The incident's `app: cluster=` line |
| `namespace` | **Required** | The incident's `app: namespace=` line |
| `app` | **Required** | The seed line's `app` (seed app only) |

**If any required input is missing, don't run any command from this skill.** Record a `missing_input` gap that names what's missing (e.g. `missing_input: app namespace`) and continue with the next step. Never guess or substitute a value, and never reuse another app's or another source's value.

Fetch config for the **seed app only**. Never for upstream or downstream apps.

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

**Config is never a source of access inputs.** The Kafka cluster and topics and the DB host and name come from the **incident** (no input, no access). The config is used for:

| Key | Used for |
|---|---|
| `kafka.consumer.topics` | Which incident topics the app **consumes** → the producers on them are **upstream** *(pending user confirmation)* |
| `kafka.producer.topics` | Which incident topics the app **produces** → the consumers of them are **downstream** *(pending user confirmation)* |
| `kafka.consumer.group` | The group for the lag check, if the incident gave no `group=` *(pending user confirmation)* |
| timeouts, retries, pool sizes, thread counts | Limits that `investigator` checks for inconsistencies (e.g. pool size below worker threads, retries × timeout longer than a consumer can wait). You don't judge these yourself |

Topics in the config that **aren't** in the incident are **not** fetched (no input, no access). The config may also name a Kafka cluster or DB that differs from the incident. Don't use the config's value. Note the mismatch in the report.
