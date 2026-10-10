---
name: incident-logs
description: Coordinator for investigating a distributed-system incident that starts from one application error line. Defines the rules, the investigation order, and which component skill to use at each step (incident-app-logs, incident-app-config, incident-kafka, incident-db-logs). Use when asked to investigate an incident or an application error. All data in this project is synthetic (MOCK).
---

# incident-logs: coordinator (v0.1)

> **v0.1 (M2).** The per-component details (how to log in, what to look for, how to search by time, cluster and topic) live in **separate component skills**. This file holds only the rules, the order, and which skill to use when.
> Coming next: **v1 (M5)** adds the full traversal procedure with `investigator plan`. **v2 (M10)** adds the report contract and links each component skill's allowlist.
> All example names and values in these skills (`example-app`, `example-cluster`, `example.in`, …) are deliberately neutral and match no scenario.

## 1. Hard rules (apply to every component skill)

1. **Start from the seed.** Your first message is one application error log line. It names the application and carries the cluster, namespace, instance, thread and (usually) correlation ID. Everything you fetch must trace back to it.
2. **Never parse raw logs or config yourself.** Fetch with the documented commands. `investigator` (deterministic code) parses, classifies, correlates and orders. You reason over its structured output only.
3. **Never decide chronology yourself.** Clocks across components can be skewed by up to a minute.
4. **Only run commands documented in a component skill, exactly as shown.** No pipes, redirects, `;`, `&&`, subshells or other tools.
5. **Always pass `--save-dir <workdir>`.** Output that isn't saved can't be used as evidence.
6. **You never log in.** Every component uses the **user's SSO session**. On an SSO error, stop and ask the user to run `mocklogs sso login`, then retry that command **once**. If the user declines or it still fails, record `auth_required` and continue.
7. **Refusals are findings.** `Forbidden` → record `access_denied`, don't retry, continue.
8. **Don't look for or use the scenario name.** It's deliberately hidden, because it would give away the answer.
9. **"Insufficient evidence" is a valid conclusion.** Prefer it to a guess.

## 2. Which skill, in which order

| Step | What | Skill | Inputs come from |
|---|---|---|---|
| 1 | The seed app's logs: same correlation ID + the seed's thread on its instance | `incident-app-logs` | The seed line: `cluster`, `namespace`, `app`, `instance`, `thread`, `correlation_id`, `ts` |
| 2 | The seed app's config (seed app **only**) | `incident-app-config` | The seed line: `cluster`, `namespace`, `app` |
| 3 | Kafka for the topics in that config: lag, messages with the correlation ID, broker/client logs | `incident-kafka` | The config: bootstrap servers, topics, consumer group |
| 4 | **One hop upstream** (the `producer_app` header on consumed topics) and **one hop downstream** (`CLIENT-ID`s of groups on produced topics): their app logs by correlation ID, plus thread | `incident-app-logs` | Kafka output: app names. Cluster/namespace: assumed to be the seed's unless the data says otherwise |
| 5 | The database named in the config, if any | `incident-db-logs` | The config: DB host + name |

**Time window:** by default, from 10 minutes before the seed's `ts` to 2 minutes after it. Widen it only if a step finds nothing. (The defaults will be tuned; `investigator plan` will compute them in v1.)

## 3. What counts as an error

You don't classify records. `investigator` labels every record **ERROR / SYMPTOM / CONTEXT / ANOMALY** with an `error_code`, per component (definitions: `docs/design/PROPOSAL.md` §2). Each component skill's "What to look for" section only helps you pick filters and notice when a step needs widening.
