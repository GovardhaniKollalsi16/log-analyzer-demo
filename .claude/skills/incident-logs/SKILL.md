---
name: incident-logs
description: Coordinator for investigating a distributed-system incident. The incident message gives one application error line plus the inputs for each source (app cluster/namespace, Kafka cluster and topics, database host and name). Defines the rules, the "no input, no access" rule, the investigation order, and which component skill to use at each step (incident-app-logs, incident-app-config, incident-kafka, incident-db-logs). All data in this project is synthetic (MOCK).
---

# incident-logs: coordinator (v0.2)

> **v0.2 (M2).** The per-component details (logging in, required inputs, searching by time, cluster and topic, what to look for) live in **separate component skills**. This file holds the rules, the incident format, the order, and which skill to use when.
> Coming next: **v1 (M5)** adds the full traversal procedure with `investigator plan`. **v2 (M10)** adds the report contract and links each component skill's allowlist. Safeguards and rate limiting will be added later by the user.
> All example names and values in these skills (`example-app`, `example-cluster`, `example.in`, …) are deliberately neutral and match no scenario.

## 1. Hard rules (apply to every component skill)

1. **No input, no access.** Every component skill lists its **required inputs**. If any required input is missing, **don't run any command from that skill.** Record a `missing_input` gap that names the missing input(s), and move on. Never guess, assume, or invent a cluster, namespace, topic, host, database or app name.
2. **Start from the incident.** Your first message is the incident: one application error line plus the inputs for each source (§2). Everything you fetch must trace back to it.
3. **Never parse raw logs or config yourself.** Fetch with the documented commands. `investigator` (deterministic code) parses, classifies, correlates and orders. You reason over its structured output only.
4. **Never decide chronology yourself.** Clocks across components can be skewed by up to a minute.
5. **Only run commands documented in a component skill, exactly as shown.** No pipes, redirects, `;`, `&&`, subshells or other tools.
6. **Always pass `--save-dir <workdir>`.** Output that isn't saved can't be used as evidence.
7. **You never log in.** Every component uses the **user's SSO session**. On an SSO error, stop and ask the user to run `mocklogs sso login`, then retry that command **once**. If the user declines or it still fails, record `auth_required` and continue.
8. **Refusals are findings.** `Forbidden` → record `access_denied`, don't retry, continue.
9. **Don't look for or use the scenario name.** It's deliberately hidden, because it would give away the answer.
10. **"Insufficient evidence" is a valid conclusion.** Prefer it to a guess. Missing inputs, missing access and missing auth all reduce what you may conclude; say which ones applied.

## 2. The incident message (proposed format, pending user review)

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
- *Pending user confirmation:* the plain `app:` line covers **only the seed app**. A related (upstream/downstream) app is fetched only if the incident has an `app[<name>]:` line for it.

## 3. Which skill, in which order

| Step | What | Skill | Required inputs (all must be present, or the step is skipped) |
|---|---|---|---|
| 1 | The seed app's logs: same correlation ID + the seed's thread on its instance | `incident-app-logs` | `app.cluster`, `app.namespace`, plus `app`, `ts` from the seed line |
| 2 | The seed app's config (seed app **only**) | `incident-app-config` | `app.cluster`, `app.namespace`, plus `app` from the seed line |
| 3 | Kafka: lag, messages with the correlation ID, broker/client logs | `incident-kafka` | `kafka.bootstrap`, `kafka.topics` (plus `kafka.group` for lag) |
| 4 | **One hop upstream** (the `producer_app` header on consumed topics) and **one hop downstream** (`CLIENT-ID`s of groups on produced topics): their app logs by correlation ID, plus thread | `incident-app-logs` | The app name from Kafka output, plus that app's `app[<name>]:` line from the incident. No line → skip that app (`missing_input`). Never reuse the seed's cluster |
| 5 | The database | `incident-db-logs` | `db.host`, `db.name` |

**Time window:** derived from the seed line's `ts`. By default, from 10 minutes before to 2 minutes after; widen once if a step finds nothing. (Defaults to be tuned; `investigator plan` will compute them in v1.)

## 4. What counts as an error

You don't classify records. `investigator` labels every record **ERROR / SYMPTOM / CONTEXT / ANOMALY** with an `error_code`, per component (definitions: `docs/design/PROPOSAL.md` §2). Each component skill's "What to look for" section only helps you pick filters and notice when a step needs widening.
