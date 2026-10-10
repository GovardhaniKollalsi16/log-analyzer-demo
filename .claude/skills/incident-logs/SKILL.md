---
name: incident-logs
description: How to fetch and investigate distributed-system incident data (application logs, application config, Kafka, database logs) starting from one application error line. Use when asked to investigate an incident or an application error. All data in this project is synthetic (MOCK).
---

# incident-logs (v0)

> **Version v0 (M2).** Covers: rules, authentication, the component → command map, exact syntax, output formats, and refusal handling.
> Coming next: **v1 (M5)** adds the full traversal procedure and `investigator plan`. **v2 (M10)** adds the machine-readable allowlist and the report contract.
> Output samples below are **illustrative** until `mocklogs` exists. They will be replaced with real generated output (see `docs/process/SKILL_CHANGELOG.md`).
> **All example names and values here (`example-app`, `example.topic`, …) are deliberately neutral.** They match no scenario, so the skill can never hint at an answer. Real samples will use a dedicated neutral fixture for the same reason.

## 1. Hard rules

1. **Start from the seed.** The first message you receive is one application error log line. It names the application. Everything you fetch must trace back to it.
2. **Never parse raw logs or config yourself.** Fetch them with the commands below and let `investigator` (deterministic code) parse, classify, correlate and order them. You reason over its structured output only.
3. **Never decide chronology yourself.** Timestamps from different components can be skewed by up to a minute. The timeline comes from `investigator`.
4. **Only run the commands documented here, exactly as shown.** No pipes, redirects, `;`, `&&`, subshells or other tools. Use the built-in `--grep` / `--save-dir` flags instead of shell tricks.
5. **Always pass `--save-dir <workdir>`** so the raw output is saved for `investigator`. Output that isn't saved can't be used as evidence.
6. **You never log in.** Authentication is the user's SSO session (§2). Never run, suggest, or simulate `sso login` yourself; ask the user.
7. **Refusals are information, not obstacles.** "Forbidden" and "SSO session expired" are recorded as coverage gaps. Don't try to work around them.
8. **Don't look for or use the scenario name.** The data is synthetic. Which scenario is loaded is deliberately hidden, because it would give away the answer. Investigate only from the data.
9. **"Insufficient evidence" is a valid conclusion.** Prefer it to a guess.

## 2. Connecting: authentication and access

There are **no agent credentials.** Every fetch command runs under the **user's SSO session**:

- The **user** authenticates by running `mocklogs sso login` in their own terminal. You never run it.
- Every fetch command checks the session first. If it's missing or expired, the command prints this (and exits with code 3):
  ```
  # MOCK DATA — synthetic, not from any real system
  error: SSO session expired or missing. Ask the user to run: mocklogs sso login
  ```
  **What to do:** stop fetching and ask the user to run `mocklogs sso login`, then retry the same command **once**. If the user declines, or it still fails, record the step as `auth_required` and continue with what you have.
- You can only see what the **user** is entitled to see. Anything outside their access prints this (and exits with code 4):
  ```
  # MOCK DATA — synthetic, not from any real system
  Error from server (Forbidden): configmaps "example-app-config" is forbidden: user cannot get resource in namespace "apps"
  ```
  **What to do:** don't retry. Record it as an `access_denied` gap and continue. Missing access lowers the confidence you're allowed to claim.

## 3. Components → commands

Four components. Each command below is the **only** supported shape. `<workdir>` is the run's working directory. Times are RFC 3339 UTC (e.g. `2026-03-14T09:10:00Z`).

### 3.1 Application logs — `kubectl logs` shape
```
mocklogs kubectl logs deploy/<app> -n apps --timestamps \
    --since-time=<rfc3339> [--until-time=<rfc3339>] \
    [--grep <correlation-id>] [--instance <pod> --thread <thread>] \
    --save-dir <workdir>
```
- `--grep` keeps lines containing the value (use it for the correlation ID).
- `--instance` + `--thread` keep lines from one thread on one pod. **Thread names are only meaningful within one app and one instance;** never compare thread names across apps or pods.
- Kafka **client** activity (producer sends, consumer processing) appears in the owning app's logs, under a `logger` that names the Kafka client.

### 3.2 Application config — `kubectl get configmap` shape
```
mocklogs kubectl get configmap <app>-config -n apps -o json --save-dir <workdir>
```
- This tells you what the app is connected to: topics it consumes (and its consumer group), topics it produces, the database it uses, and limits such as timeouts, retries and pool sizes.
- Fetch config **only for the seed application.**

### 3.3 Kafka
Consumer-group lag (`kafka-consumer-groups` shape):
```
mocklogs kafka-consumer-groups --describe --group <group> [--samples 3] --save-dir <workdir>
mocklogs kafka-consumer-groups --describe --all-groups --save-dir <workdir>
```
- `--samples N` (mock extension) prints N lag snapshots taken one minute apart, standing in for polling the real tool repeatedly. Use it to tell **growing** lag from steady lag.
- `--all-groups` lists every group with its topics and `CLIENT-ID`s. This is how **downstream** consumers of a topic are identified.

Messages (`kafka-console-consumer` shape):
```
mocklogs kafka-console-consumer --topic <topic> --from-beginning \
    --property print.headers=true --property print.timestamp=true \
    --property print.partition=true --property print.offset=true \
    --grep <correlation-id> [--max-messages <n>] --save-dir <workdir>
```
- Message headers carry `correlation_id` and `producer_app`. `producer_app` on a topic the seed app **consumes** names the **upstream** application.
- `--grep` is a mock extension (the real tool would be piped to `grep`, which you're not allowed to do).

Broker and client logs:
```
mocklogs kafka logs --component broker|producer|consumer --topic <topic> \
    --since-time=<rfc3339> [--until-time=<rfc3339>] --save-dir <workdir>
```

### 3.4 Database logs
```
mocklogs db logs --db <name> --since-time=<rfc3339> [--until-time=<rfc3339>] \
    [--grep <app>] --save-dir <workdir>
```
- Fetch these only if the seed app's config declares a database.
- Filter with `--grep <app>` to keep that application's sessions.

## 4. Output formats (illustrative until `mocklogs` exists)

Every output's **first line** is the MOCK banner:
```
# MOCK DATA — synthetic, not from any real system
```

**Application log** (`kubectl logs --timestamps`): an RFC 3339 prefix, then one JSON object per line:
```
2026-01-01T00:00:01.250000000Z {"ts":"2026-01-01T00:00:01.250Z","level":"ERROR","app":"example-app","instance":"example-app-5c6d7-0","thread":"worker-2","logger":"example.Handler","correlation_id":"c-0000","msg":"Request failed","error":{"type":"ExampleException","message":"example failure"}}
```
Fields: `ts`, `level`, `app`, `instance`, `thread`, `logger`, `correlation_id` (may be missing), `msg`, optional `error{type, message, stack}`.

**Application config** (`kubectl get configmap -o json`):
```
{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"example-app-config","namespace":"apps"},
 "data":{"kafka.consumer.topics":"example.in","kafka.consumer.group":"example-app-group",
         "kafka.producer.topics":"example.out","db.name":"example-db","http.client.timeout.ms":"5000"}}
```

**Consumer-group lag** (`kafka-consumer-groups --describe`):
```
GROUP              TOPIC       PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID       HOST        CLIENT-ID
example-app-group  example.in  0          1200            1200            0    consumer-1-0000   /10.0.0.1   example-app
```
With `--samples N`, each snapshot is preceded by `# sample k/N at <rfc3339>`.

**Messages** (`kafka-console-consumer` with print properties): tab-separated timestamp, partition, offset, headers, value:
```
CreateTime:1767225600000	Partition:0	Offset:1199	correlation_id:c-0000,producer_app:example-upstream	{"id":"x-1","payload":"..."}
```

**Kafka broker/client logs:** log4j-style text:
```
[2026-01-01 00:00:00,500] INFO [Consumer clientId=example-app-1, groupId=example-app-group] Setting offset for partition example.in-0 to the committed offset 1200 (org.apache.kafka.clients.consumer.internals.ConsumerCoordinator)
```

**Database log:** postgres-style `log_line_prefix` text:
```
2026-01-01 00:00:02.000 UTC [1001] app=example-app user=example db=example-db LOG:  connection authorized: user=example database=example-db
```

## 5. What counts as an error

You don't classify records yourself. `investigator` classifies every record per component as **ERROR** (failed), **SYMPTOM** (degraded), **CONTEXT** (normal), or **ANOMALY** (config only), each with an `error_code`. The definitions are in `docs/design/PROPOSAL.md` §2. Cite the classified events by their `event_id`.

## 6. Investigation order (summary; full procedure in v1)

1. Seed app logs: correlation ID, plus the seed's thread on its instance.
2. Seed app config.
3. Kafka for the topics in that config: lag, messages with the correlation ID, broker/client logs.
4. One hop **upstream** (the `producer_app` on consumed topics) and one hop **downstream** (`CLIENT-ID`s of groups on produced topics): their app logs by correlation ID and thread.
5. The database from the config, if any.

In v1, `investigator plan --workdir <workdir>` will tell you the exact next commands.
