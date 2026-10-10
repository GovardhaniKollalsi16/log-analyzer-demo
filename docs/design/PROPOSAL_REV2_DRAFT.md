# Design Proposal: Revision 2 DRAFT (seed-driven traversal)

Status: **Draft written 2026-10-10 while the user was editing `PROPOSAL.md`.** Kept in a separate file so it doesn't overwrite their edits. Once the user approves it, it gets merged into `PROPOSAL.md` (with their edits preserved) and this file is deleted. Source of the change: PROMPT_LOG entry 014. M1 code is on hold and needs the model changes in §3.1 once this is approved.

User edit seen in `PROPOSAL.md` at 10:48: "data-quality issues" was removed from the bundle description. **Open question Q1 (§8):** does that also mean dropping `parse_issues` and the `data_quality` confidence factor? This draft keeps both until answered.

## 0. What changed from Rev 1

| Area | Rev 1 | Rev 2 |
|---|---|---|
| Components | app logs, upstream dependency, Kafka, DB (logs + server config) | **app logs, app config, Kafka logs, DB logs** |
| Entry point | Fan out to every source | **One seed: an application error log line that names the app** |
| Order | app → upstream → Kafka → DB | **seed app log → that app's config → Kafka in/out → related app logs (upstream/downstream) → downstream DB** |
| Linking keys | correlation/trace/message/request IDs | Same IDs **+ thread number (within one app instance)** |
| "Error" | Generic: level ERROR/CRITICAL | **Defined per component** (§2) |
| Who decides what to fetch next | The LLM, guided by SKILL.md | **Deterministic `investigator plan`** reads the config and fetched data and emits the next fetches; the LLM runs them |

## 1. Architecture & data flow

```
 seed: app error log line (names the app)
   │
   ▼
 ┌─────────────────────────── traversal (ordered) ───────────────────────────┐
 │ 1. seed app logs ── same correlation ID + same thread segment             │
 │ 2. seed app CONFIG (only if access) ─► topology: topics in/out, consumer  │
 │                                         group, downstream DB, timeouts     │
 │ 3. KAFKA for those topics: consumer-group lag, producer/consumer logs,     │
 │    message headers (correlation ID, producing app)                         │
 │ 4. RELATED APP LOGS: upstream producers + downstream consumers, filtered   │
 │    by common identifier, extended by thread segment                        │
 │ 5. DOWNSTREAM DB logs (only if the config declares a DB)                   │
 └───────────────────────────────────────────────────────────────────────────┘
   each step: agent runs allowlisted `mocklogs ...` → saves raw output
              → `investigator plan` (deterministic) says what to fetch next
   │
   ▼
 investigator correlate (deterministic, no LLM)
   parse/normalize → classify errors per component → dedupe → link
   (IDs + thread segments) → timeline (skew-tolerant) → detectors
   → hypotheses + confidence cap → ANALYSIS BUNDLE (JSON)
   │
   ▼
 LLM reasons over the bundle only ─► submit_report ─► validator
   (event IDs must exist, confidence ≤ cap, 3 retries then INSUFFICIENT)
   ─► report.json + report.md, transcript ─► runs/<ts>-<scenario>.jsonl
```

**Traversal rules**
- **Step 1, seed.** The investigation starts from one application error record. From it, the code extracts the app name, instance, thread, timestamp, correlation ID and error code. Fetch that app's logs around the seed time (± skew tolerance), filtered by correlation ID, plus the seed's **thread segment** (§1.1).
- **Step 2, config.** Fetch the seed app's config. If access is denied, that's a recorded coverage gap rather than a crash, and it lowers the confidence cap. The config gives the topology: consumed topics + consumer group, produced topics, downstream DB(s), timeouts/retries/pool sizes. It also gives recent config **changes** with timestamps.
- **Step 3, Kafka.** For each topic in the topology:
  - consumer-group lag for the app's group;
  - producer/consumer logs;
  - messages carrying the seed's correlation ID, with headers.
  Message headers name the **producing app** (upstream). Consumer groups on the produced topics name the **consuming apps** (downstream, via CLIENT-ID).
- **Step 4, related apps.** Fetch logs for upstream/downstream apps filtered by the common identifier. Each hit is extended by its thread segment. The default depth is 1 hop each way (D15).
- **Step 5, DB.** Only if the config declares a downstream DB. Fetch DB logs in the incident window, filtered by the app's DB user / application name / connection IDs where present.
- **Stop conditions:**
  - the plan has no remaining fetches;
  - hop limit reached;
  - every remaining target is access-denied;
  - the turn budget is spent.

### 1.1 Thread segments (how thread numbers are used)

Thread numbers are **not** global IDs. Thread pools reuse threads, and two apps can both have `worker-7`. So a thread link is only valid within **one app + one instance**.

A thread segment is the run of lines on `(app, instance, thread)` around an ID-carrying line. It extends until the same thread logs a **different** correlation ID, or until the gap exceeds the tolerance. This captures the ID-less lines (retry attempts, stack traces, "giving up") that belong to the same unit of work. Such links are labeled `THREAD_LOCAL` and are never treated as strong as an exact ID match.

## 2. Error definitions per component

Every parsed record is classified deterministically into one of:
- **ERROR**: the component failed to do its job;
- **SYMPTOM**: degraded, but not failed;
- **CONTEXT**: normal activity useful for chronology;
- **ANOMALY**: config only.

Each non-CONTEXT record also gets a stable `error_code`. Classification is rule tables in `investigator/classify/`, keyed on structure and patterns, **never on app/topic names**. Thresholds are configurable.

### 2.1 Application logs
| Class | Rule | Example `error_code`s |
|---|---|---|
| ERROR | level ERROR/FATAL; or any record with an exception + stack trace that is not followed by a success for the same correlation ID; or "retries exhausted"/"giving up"; or an outbound call/publish failure after the final attempt | `app.exception`, `app.retries_exhausted`, `app.outbound_timeout`, `app.publish_failed`, `app.db_call_failed` |
| SYMPTOM | WARN with an exception that later succeeds (transient); individual retry attempts; latency above the configured timeout × 0.8; circuit breaker open; thread-pool / queue saturation warnings | `app.retry_attempt`, `app.slow_call`, `app.circuit_open`, `app.pool_saturated` |
| CONTEXT | INFO/DEBUG request start/end, message received/processed, config loaded | — |
| Not an error | Expected business rejections explicitly marked as handled (e.g. validation failures returned to the caller) | — |

### 2.2 Application config
Config is not a log, so it has no ERROR class. It produces **ANOMALY** records, each citing the config key (and the change record, if any):
| Rule | `error_code` |
|---|---|
| Key changed within the incident window (change timestamp ≥ window start and ≤ first ERROR) | `config.recent_change` |
| Internal inconsistency, e.g. `retries × request_timeout` > the consumer's max poll interval; client timeout < observed upstream latency; pool size < configured worker concurrency | `config.inconsistent` |
| Reference to a resource the traversal could not find (topic absent in Kafka, DB never seen in logs) | `config.dangling_reference` |
| Missing/invalid required key (unparseable duration, negative size) | `config.invalid_value` |
| Access denied to the config | *(coverage gap, not an anomaly)* |

### 2.3 Kafka logs
| Sub-component | ERROR | SYMPTOM |
|---|---|---|
| Producer | delivery failed after retries, record expired / delivery timeout, send buffer exhausted, authorization failure | individual send retry, request latency above threshold, metadata refresh failures that recover |
| Broker | request rejected for the topic, partition offline / no leader | ISR shrink, under-replicated partition, leader election |
| Consumer | processing exception (no commit) for a message, deserialization failure, commit failure, message sent to dead-letter topic, max poll interval exceeded / kicked from group | rebalance, redelivery of the same message offset |
| Consumer-group lag (metric) | lag growing across ≥ N consecutive samples **and** above threshold, or one partition stuck at the same committed offset | lag above threshold but not growing |

### 2.4 DB logs
| Class | Rule | Example `error_code`s |
|---|---|---|
| ERROR | severity ERROR/FATAL/PANIC; connection refused / too many connections; authentication failure; deadlock detected; statement cancelled by timeout; transaction aborted | `db.connection_refused`, `db.too_many_connections`, `db.deadlock`, `db.statement_timeout`, `db.auth_failed` |
| SYMPTOM | slow query above threshold; lock wait above threshold; connection count near limit | `db.slow_query`, `db.lock_wait`, `db.connections_high` |
| CONTEXT | connection received/authorized, checkpoints, routine statements | — |

## 3. Module structure

```
pyproject.toml
src/
  mocklogs/                    # MOCK data side. Analysis code must NEVER import this.
    cli.py                     # kubectl logs / kubectl get configmap / config history /
                               # kafka-consumer-groups / kafka-console-consumer / kafka logs / db logs
    access.py                  # mock access list: which app configs/logs the agent may read
    scenarios/                 # seeded, parameterized generators
    render.py                  # native-looking formats + MOCK banner
  investigator/
    models.py
    adapters/                  # LogSource protocol; MockCliSource (allowlisted argv, no shell)
    parsing/                   # one parser per format → Event | ParseIssue
    normalize.py               # UTC, levels, IDs, thread/instance extraction, stable event_id
    classify/                  # §2 rule tables: app.py, config.py, kafka.py, db.py
    config_model.py            # config dump + history → ConfigEntry, AppTopology
    planner.py                 # seed + topology + fetched data → FetchPlan (next allowlisted commands)
    dedupe.py
    correlation.py             # union-find over IDs + THREAD_LOCAL segments
    timeline.py                # skew estimation, tolerance ordering (D2: 60 s), uncertainty flags
    detectors/                 # cross-record patterns over classified events (never names)
    analysis.py                # hypotheses, confidence factors + cap, coverage gaps, bundle
    allowlist.py               # fenced JSON allowlist in SKILL.md
    agent/  provider.py  loop.py  tools.py
    narration.py
    report/  model.py  validate.py  render_md.py
    cli.py                     # investigator plan | correlate | run | validate | replay
.claude/
  skills/incident-logs/SKILL.md
  agents/incident-investigator.md
  hooks/allowlist_guard.py
tests/  unit/  integration/  robustness/
```

### 3.1 Data models (changes from Rev 1 marked ★; M1 code must be updated)

- ★ `Source`: `APP`, `APP_CONFIG`, `KAFKA`, `DB` (Rev 1's `UPSTREAM` removed, D13).
- ★ `Severity`: `ERROR | SYMPTOM | CONTEXT | ANOMALY` (§2), separate from the log's own `Level`.
- `RawRecord`, `ParseIssue`, `Ids(correlation_id, trace_id, message_id, request_id)`: unchanged (but see Q1).
- `Event`: as in M1, ★ plus `app`, `instance`, `thread`, `severity`, `error_code`, `kafka: Optional[KafkaRef(topic, partition, offset, group, client_id)]`.
- ★ `Seed(event_id, app, instance, thread, ts_utc, correlation_id, error_code)`
- ★ `ConfigEntry(app, key, value, changed_at, previous_value, raw_ref)`
- ★ `AppTopology(app, consumes: [(topic, group)], produces: [topic], databases: [name], limits: {key: value})`
- ★ `FetchStep(order, component, target, argv, reason, hop)` and `FetchPlan(steps, done: bool, stop_reason)`
- ★ `CoverageGap(component, target, reason: access_denied | not_found | empty | hop_limit)`
- `CorrelationGroup`: ★ `LinkKind` gains `THREAD_LOCAL`; `WEAK_TEMPORAL` stays labeled and is used only as a last resort.
- `TimelineEntry`, `SkewEstimate`, `Finding`, `Hypothesis`, `ConfidenceFactor`: unchanged.
- `AnalysisBundle`: ★ plus `seed`, `topology`, `coverage_gaps: [CoverageGap]`, `traversal: [FetchStep]` (what was fetched and why).
- `IncidentReport` (M9): unchanged sections. The timeline and evidence now also show `app/instance/thread`.

**Confidence factors (★ revised):** `id_linkage` (exact vs thread-local vs weak), `traversal_coverage` (steps completed vs access-denied/missing), `temporal_precedence`, `competing_hypotheses`, `data_quality` (see Q1).

## 4. Scenarios (seed-driven)

Generic names (D6): `edge-gateway`, `order-api`, `fulfillment-worker`, `notification-worker`, external HTTP dependency `partner-pricing` (no logs of its own, visible only through app logs, D13), topic `orders.events`, group `fulfillment-consumers`, DB `appdb`.

| # | Seed (what the agent is handed) | What the traversal should surface (generator ground truth, never visible to `investigator`) |
|---|---|---|
| 1 upstream-timeout | `order-api` ERROR: publish failed | Thread segment shows `partner-pricing` call timeouts + retries; config shows a high retry count × timeout; Kafka producer delivery timeouts; downstream consumer sees a gap |
| 2 db-config | `fulfillment-worker` ERROR: DB call failed | Config history: DB pool size / statement timeout changed shortly before; DB logs show statement timeouts / too many connections from that app |
| 3 consumer-lag | `notification-worker` ERROR: entity not found (a downstream symptom) | Upstream via headers to `fulfillment-worker`; repeated consumer processing failures on one offset (poison message); lag growing on one partition |
| 4 ambiguous | an ERROR with **no correlation ID** | Config access denied for one app; scattered SYMPTOMs, no ID chain → **INSUFFICIENT** |

Knobs (D8): `seed`, `service_names` (renames apps, topics, groups, **thread names, instances**), `t0`, `per_source_skew_ms`, `drop_rate`, `dup_rate`, `shuffle`, `malformed_rate`, ★ `access_denied` set.

## 5. SKILL.md outline

1. Purpose & hard rules: start from the seed; never parse raw logs or config yourself; let `investigator plan` choose the next fetch; cite bundle event IDs only; INSUFFICIENT is a valid answer.
2. The traversal order (§1) and stop conditions.
3. Component → command map, with exact syntax:
   - app logs: `mocklogs kubectl logs deploy/<app> -n <ns> --since=<dur> --timestamps [--grep <id>] [--thread <t> --instance <pod>]`
   - app config: `mocklogs kubectl get configmap <app>-config -n <ns> -o json`, `mocklogs config history <app> --since=<dur>`
   - Kafka:
     - `mocklogs kafka-consumer-groups --describe --group <g>`
     - `mocklogs kafka-console-consumer --topic <t> --grep <id> --property print.headers=true`
     - `mocklogs kafka logs --component producer|broker|consumer --topic <t> --since=<dur>`
   - DB logs: `mocklogs db logs --db <name> --since=<dur> [--grep <app>]`
   - deterministic: `investigator plan --workdir <dir>`, `investigator correlate --workdir <dir> --json`
4. Output format per command, with an annotated sample including the MOCK banner and the access-denied message.
5. What counts as an error per component: a short pointer to §2. The code classifies; the agent doesn't.
6. Reading the bundle: seed, traversal, coverage gaps, findings, hypotheses, cap.
7. Report contract: required sections, citations, confidence ≤ cap.
8. Allowlist (fenced JSON, D1), one entry per command shape above.

## 6. Technical risks & assumptions (new ones marked ★; R1–R11 carry over from Rev 1)

| # | Risk / assumption | Mitigation |
|---|---|---|
| ★ R12 | **Thread reuse** creates false links (a pooled thread serves many requests). | Links only within app+instance; segment ends at a different correlation ID or a gap > tolerance; labeled `THREAD_LOCAL`, weaker than an exact ID. Tests interleave two requests on one thread. |
| ★ R13 | **Finding upstream producers.** Real Kafka doesn't list producers per topic. | Rely on message headers (producing app + correlation ID), which is a common convention. If a header is missing → coverage gap, and no guessing. |
| ★ R14 | Traversal blow-up (fan-out across topics/apps). | Hop limit (D15), dedupe of fetch targets, and the turn budget. The planner records `hop_limit` gaps. |
| ★ R15 | Error definitions are judgment calls; thresholds may misclassify. | All rules in one table per component, each with a unit test and a configurable threshold. The user reviews the tables in M4 before detectors depend on them. |
| ★ R16 | Seed without a correlation ID (scenario 4). | Thread segment + time window only, all links labeled weak, so the cap can't exceed LOW. |
| R5 (updated) | Root cause leaking into analysis code. | Boundary test (M1) + rule tables on structure, not names + robustness renames **including threads/instances**. |

## 7. Milestone plan (replaces Rev 1 M2–M12)

| M | Scope |
|---|---|
| M0 ✅ | Process + design (Rev 1). Rev 2 = this draft, awaiting review |
| M1 🟡 | Skeleton + models. **Needs a §3.1 update after Rev 2 approval** |
| M2 | `mocklogs`: 4 components, access control, scenario 1 |
| M3 | Parsing + normalization (incl. thread/instance) + dedupe |
| M4 | **Per-component error classification (§2)**; the user reviews the rule tables |
| M5 | **Config → topology + `investigator plan` (traversal planner)** |
| M6 | Correlation (IDs + thread segments) + timeline |
| M7 | Detectors + `investigator correlate` → bundle |
| M8 | Scenarios 2–4 + robustness matrix |
| M9 | Report model + validator + Markdown |
| M10 | SKILL.md + JSON allowlist + command runner |
| M11 | Provider interface, fake LLM, tool loop, transcripts |
| M12 | Anthropic provider + replay (needs API key) |
| M13 | Claude Code subagent + hook + transcript capture |
| M14 | README + demo |

`MILESTONES.md` will be rewritten to match once this is approved.

## 8. New open decisions (D1–D12 unchanged; D5 gets amended)

| # | Decision | Proposed |
|---|---|---|
| Q1 | Your 10:48 edit removed "data-quality issues" from the bundle | Keep `parse_issues` + the `data_quality` factor in the bundle (malformed/duplicate handling is a stated requirement), or drop them from the bundle and only log them? |
| D13 | External HTTP upstream (`partner-pricing`) | No longer a separate log source; visible only through app logs (timeouts/retries) |
| D14 | DB server config (psql `SHOW ALL`) | Drop it; DB-related config lives in the **app** config (pool size, statement timeout). DB logs stay |
| D15 | Traversal depth | 1 hop upstream + 1 hop downstream by default, configurable up to 2 |
| D16 | Access model | Mock access list; denied → "ACCESS DENIED" output + coverage gap; cap ≤ MEDIUM if a step on the seed's direct path is denied |
| D17 | Thread segment boundary | Ends at a different correlation ID on the same thread, or a gap > skew tolerance |
| D18 | Who plans the traversal | Deterministic `investigator plan`; the LLM executes and may skip a step only with a stated reason |
| D19 | Seed input | One raw app log line, passed as `--seed-file` or as the agent's first message |
| D20 | Config change history | `mocklogs config history <app>` (like a config-service audit log) so `config.recent_change` is detectable |
| D5 amend | Mock formats | App logs JSON lines now include `instance` and `thread`; app config as `kubectl get configmap -o json` |
