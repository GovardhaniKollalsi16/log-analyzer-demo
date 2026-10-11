# Design Proposal: Revision 2 (seed-driven traversal)

Status: **Rev 2 approved 2026-10-10 (PROMPT_LOG entry 018).** M1 (models per §3.1) approved and pushed 2026-10-10. M1 code is on hold until then, and needs the model changes in §3.1. Rev 1 is in git history (`git show d15deee:docs/design/PROPOSAL.md`, which includes the user's own Rev 1 edit).

## 0. What changed from Rev 1

| Area | Rev 1 | Rev 2 |
|---|---|---|
| Components | app logs, HTTP upstream dependency, Kafka, DB logs + DB server config | **app logs, app config, Kafka logs, DB logs** (D13, D14) |
| Entry point | Fan out to every source | **One seed: an app error log line, given as the agent's first message** (D19) |
| Order | app → upstream → Kafka → DB | **seed app log → its config → Kafka in/out → related apps (1 hop up, 1 hop down) → downstream DB** (D15) |
| Linking keys | correlation/trace/message/request IDs | Same IDs **+ thread number within one app instance, 1-min window** (D17) |
| "Error" | Generic: level ERROR/CRITICAL | **Defined per component** (§2) |
| Next fetch decided by | The LLM | **Deterministic `investigator plan`** (D18) |
| Data-quality issues in the bundle | Yes | **No** (Q1) |
| Config change history | n/a | **Not used** (D20) |

## 1. Architecture & data flow

```
 agent's first message = seed app error log line (names the app)
   │
   ▼
 ┌─────────────────────────── traversal (ordered) ───────────────────────────┐
 │ 1. SEED APP LOGS: same correlation ID + the seed's thread segment         │
 │ 2. SEED APP CONFIG (only if access): topics consumed/produced, consumer   │
 │    group, downstream DB, timeouts/retries/pool sizes                      │
 │ 3. KAFKA for those topics: consumer-group lag, producer/consumer logs,     │
 │    messages with headers (correlation ID, producing app)                   │
 │ 4. RELATED APP LOGS, exactly 1 hop: upstream producers of consumed topics  │
 │    + downstream consumers of produced topics, filtered by the common ID,   │
 │    extended by thread segment                                              │
 │ 5. DOWNSTREAM DB LOGS (only if the config declares a DB)                   │
 └───────────────────────────────────────────────────────────────────────────┘
   each step: agent runs the allowlisted `mocklogs ...` → raw output saved
              → `investigator plan` (deterministic) emits the next fetches
   │
   ▼
 investigator correlate (deterministic, no LLM)
   parse/normalize → classify per component (§2) → dedupe → link
   (IDs + thread segments) → timeline (by timestamp, D30) → detectors
   → hypotheses + confidence cap → ANALYSIS BUNDLE (JSON)
   │
   ▼
 LLM reasons over the bundle only ─► submit_report ─► validator
   (event IDs must exist, confidence ≤ cap, 3 retries then INSUFFICIENT)
   ─► report.json + report.md; transcript ─► runs/<ts>-<scenario>.jsonl
```

> **Amended 2026-10-10 (user, D22/D23):** the agent's first message is an **incident**: the seed error line **plus the inputs for each source** (app cluster/namespace, Kafka bootstrap + topics, DB host + name). **No input, no access:** a step whose required inputs aren't in the incident isn't run; it's recorded as a `missing_input` coverage gap. The config is **no longer a source of access inputs**. It's used for topic direction (consume vs. produce), the consumer group, and limits. Where the step text below says the config supplies topics or the DB, read it as "the incident supplies them". The skills are authoritative.

**Traversal rules**
- **Step 1, seed.** The seed line is the agent's first message (D19). The runtime saves it verbatim to the run's workdir as `seed.log`, and `investigator plan` parses it. The LLM doesn't extract fields from it. From the seed, the code gets the app, instance, thread, timestamp, correlation ID and error code. Fetch that app's logs around the seed time, filtered by correlation ID, plus the seed's thread segment (§1.1).
- **Step 2, config.** Fetch the seed app's config. If access is denied, it's recorded as a coverage gap that lowers the confidence cap (D16)(Yes this is important), not a crash. The config yields the topology: consumed topics + group, produced topics, downstream DB(s), timeouts/retries/pool sizes. **No change history is used** (D20).
- **Step 3, Kafka.** For each topic in the topology:
  - consumer-group lag for the app's group;
  - producer/consumer logs;
  - messages with the seed's correlation ID, with headers.
  Headers on consumed topics name the **upstream producing app**. Consumer groups (CLIENT-ID) on produced topics name the **downstream consuming apps**. Upstream relationships are Kafka-only (D13).
  **Authentication (D21):** every fetch (app logs, config, Kafka, DB logs) runs under the user's own SSO session. There are no agent credentials. See §1.2.
- **Step 4, related apps.** Exactly one hop upstream and one hop downstream (D15). Fetch their logs filtered by the common identifier, then extend each hit by its thread segment. Their configs are not fetched (confirmed).
- **Step 5, DB.** Only if the seed app's config declares a downstream DB. Fetch DB logs in the incident window, filtered by the app's DB user / application name where present.
- **Stop conditions:**
  - no remaining planned fetches;
  - every remaining target is access-denied;
  - the turn budget is spent.

### 1.0 Correlation keys (D25, user decision 2026-10-10)

**`correlation_id` is per app, for in-app log search only.** Each service, and each sub-service inside a service, has its own correlation ID, so it never links records **across** services. Cross-service correlation uses a **business key**, chosen from the seed record by a rule table that the user maintains in the coordinator skill (`incident-logs` §3, machine-readable JSON block):

| Seed record's source class (last segment of `logger`) | Business key |
|---|---|
| `Order*` | `order_id` |
| `Product*` | `product_id` |
| *(more rules to come from the user)* | |

- The key's **value** is read from the seed record's structured field of the same name (e.g. `"order_id":"o-1008"`). No match, or a missing field, means no business key, and cross-service steps get `missing_input` (D22).
- Where the key lives:
  - app logs: a structured field (`order_id` / `product_id`);
  - Kafka: the message value field of the same name;
  - DB logs: the column of the same name in statements.
- A Kafka message header `correlation_id` is the **producer's own** ID. It's only usable to search the **producer's** app logs, never as a cross-service key.
- `investigator` links by `(app, correlation_id)` **within** an app and by the business key **across** apps.

### 1.1 Thread segments

Thread numbers are not global IDs: pools reuse threads, and two apps can both have `worker-7`. A thread link is only valid within **one app + one instance**.

The segment around an ID-carrying line covers the same `(app, instance, thread)` lines **within 1 minute** (D17). It stops early if that thread starts logging a **different** correlation ID. This picks up the ID-less lines (retry attempts, stack traces, "giving up") of the same unit of work. Such links are labeled `THREAD_LOCAL` and are weaker than an exact-ID match.

### 1.2 Authentication via the user's SSO (D21)

There are no agent login credentials. **Every** `mocklogs` fetch command (app logs, app config, Kafka, DB logs) authenticates with the **user's existing SSO session**:
- **The user logs in, never the agent.** The user runs `mocklogs sso login` themselves. In the mock it writes a session file with an expiry and a MOCK, non-secret session marker. `sso login` is **not** in the agent's allowlist, so the agent can never start or complete a login and never sees or types credentials.
- **Every fetch command checks the session.** Before returning output, `kubectl logs`, `kubectl get configmap`, `kafka-*` and `db logs` all check the session. If it's missing or expired, the command prints `SSO session expired or missing. Ask the user to run: mocklogs sso login` (MOCK) and exits non-zero.
- **On that message the agent stops and asks the user** to re-authenticate. It never retries in a loop. If the user declines, the remaining steps are recorded as `CoverageGap(reason=auth_required)`, which lowers the cap the same way an access denial does.
- **Permissions = the user's permissions.** The agent acts with the user's identity, so it can see exactly what the user can see. The D16 access list is modeled as the user's entitlements.
- **No session material in artifacts.** The session marker is never printed by any command, never written to `runs/` transcripts or reports, and transcripts are scanned for it in tests.
- **Real integration later:** the mock check is swapped for the real tool's SSO-backed auth (e.g. a CLI that uses the user's SSO token cache). The agent-side behavior stays the same.

## 2. Error definitions per component

Every parsed record is classified deterministically into one of:
- **ERROR**: the component failed to do its job;
- **SYMPTOM**: degraded, but not failed;
- **CONTEXT**: normal activity useful for chronology;
- **ANOMALY**: config only.

Each non-CONTEXT record gets a stable `error_code`. The rules live in `investigator/classify/`, keyed on structure and patterns, **never on app/topic names**. Thresholds are configurable. The user reviews these tables in M4.

### 2.1 Application logs
| Class | Rule | Example `error_code`s |
|---|---|---|
| ERROR | level ERROR/FATAL; exception + stack trace not followed by a success for the same correlation ID; "retries exhausted"/"giving up"; outbound call or publish failure after the final attempt; timed out waiting for an expected Kafka event | `app.exception`, `app.retries_exhausted`, `app.publish_failed`, `app.event_wait_timeout`, `app.db_call_failed` |
| SYMPTOM | WARN with an exception that later succeeds (transient); individual retry attempts; slow call (> 0.8 × configured timeout); circuit breaker open; thread-pool / queue saturation | `app.retry_attempt`, `app.slow_call`, `app.circuit_open`, `app.pool_saturated` |
| CONTEXT | INFO/DEBUG request start/end, message received/processed, config loaded | — |
| Not an error | Business rejections explicitly marked as handled (e.g. validation failures returned to the caller) | — |

### 2.2 Application config (ANOMALY only; no change history, D20)
| Rule | `error_code` |
|---|---|
| Internal inconsistency, e.g. `retries × request_timeout` > the consumer max poll interval; DB pool size < worker concurrency; DB statement timeout below normal query durations seen in DB logs | `config.inconsistent` |
| Reference to a resource the traversal couldn't find (topic absent in Kafka, DB never seen in logs) | `config.dangling_reference` |
| Missing/invalid required key (unparseable duration, negative size) | `config.invalid_value` |
| Access denied | *(coverage gap, not an anomaly)* |

### 2.3 Kafka logs
| Sub-component | ERROR | SYMPTOM |
|---|---|---|
| Producer | delivery failed after retries; record expired / delivery timeout; send buffer exhausted; authorization failure | individual send retry; request latency above threshold; recovered metadata refresh failure |
| Broker | request rejected for the topic; partition offline / no leader | ISR shrink; under-replicated partition; leader election |
| Consumer | processing exception without commit; deserialization failure; commit failure; message sent to dead-letter topic; max poll interval exceeded / removed from group | rebalance; redelivery of the same offset |
| Consumer-group lag | lag growing across ≥ N consecutive samples **and** above threshold; or a partition stuck at one committed offset | lag above threshold but not growing |

### 2.4 DB logs
| Class | Rule | Example `error_code`s |
|---|---|---|
| ERROR | severity ERROR/FATAL/PANIC; connection refused / too many connections; authentication failure; deadlock detected; statement cancelled by timeout; transaction aborted | `db.connection_refused`, `db.too_many_connections`, `db.deadlock`, `db.statement_timeout`, `db.auth_failed` |
| SYMPTOM | slow query above threshold; lock wait above threshold; connection count near limit | `db.slow_query`, `db.lock_wait`, `db.connections_high` |
| CONTEXT | connections received/authorized, checkpoints, routine statements | — |

### 2.5 Malformed records (Q1)
Data-quality issues are **not** part of the bundle and are not a confidence factor. The engineering rule still holds: parsers must not crash on malformed, duplicate, or out-of-order records. Malformed lines are skipped. The parser returns them only so tests can assert they were handled.

## 3. Module structure

```
pyproject.toml
src/
  mocklogs/                    # MOCK data side. Analysis code must NEVER import this.
    cli.py                     # kubectl logs / kubectl get configmap / kafka-consumer-groups /
                               # kafka-console-consumer / kafka logs / db logs
    access.py                  # mock access list = the user's entitlements (D16)
    sso.py                     # mock SSO session: `sso login` (user-only) + session check on every fetch command (D21)
    scenarios/                 # seeded, parameterized generators
    render.py                  # native-looking formats + MOCK banner
  investigator/
    models.py
    adapters/                  # LogSource protocol; MockCliSource (allowlisted argv, no shell)
    parsing/                   # one parser per format → Event (malformed lines skipped)
    normalize.py               # UTC, levels, IDs, app/instance/thread, stable event_id
    classify/                  # §2 rule tables: app.py, config.py, kafka.py, db.py
    config_model.py            # configmap JSON → ConfigEntry, AppTopology
    planner.py                 # seed + topology + fetched data → FetchPlan
    dedupe.py
    correlation.py             # union-find over IDs + THREAD_LOCAL segments
    timeline.py                # chronological order by UTC timestamp (D30: no clock-drift handling)
    detectors/                 # cross-record patterns over classified events (never names)
    analysis.py                # hypotheses, confidence factors + cap, coverage gaps, bundle
    allowlist.py               # fenced JSON allowlist in SKILL.md
    agent/  provider.py  loop.py  tools.py
    narration.py
    report/  model.py  validate.py  render_md.py
    cli.py                     # investigator plan | correlate | run | validate | replay
.claude/
  skills/incident-logs/SKILL.md         # coordinator: rules, order, which component skill when
  skills/incident-app-logs/SKILL.md     # login, inputs, search by time/cluster/correlation ID/thread, signals
  skills/incident-app-config/SKILL.md   # login, cluster/namespace, what to read (bootstrap, topics, DB, limits)
  skills/incident-kafka/SKILL.md        # login, cluster (bootstrap), topic, time→offsets, lag, up/downstream discovery
  skills/incident-db-logs/SKILL.md      # login, DB host/name, search by time/app, signals
  agents/incident-investigator.md
  hooks/allowlist_guard.py
tests/  unit/  integration/  robustness/
```

### 3.1 Data models (★ = change from M1 code, applied once Rev 2 is approved)

- ★ `Source`: `APP`, `APP_CONFIG`, `KAFKA`, `DB` (`UPSTREAM` removed).
- ★ `Severity`: `ERROR | SYMPTOM | CONTEXT | ANOMALY`, separate from the log's `Level`.
- `RawRecord`, `Ids(correlation_id, trace_id, message_id, request_id)`: unchanged.
- ★ `ParseIssue`: kept only as a parser return value for tests; **not** in the bundle (Q1).
- `Event`: ★ plus `app`, `instance`, `thread`, `severity`, `error_code`, `kafka: Optional[KafkaRef(topic, partition, offset, group, client_id, producer_app)]`.
  - As implemented in the M1 update: M1's `service` field was **replaced** by `app` (not kept alongside it), and `component` holds the sub-part (producer/broker/consumer/db-server).
  - Invariants are enforced at construction:
    - `error_code` is set exactly when severity ≠ CONTEXT;
    - ANOMALY only for `APP_CONFIG`;
    - `thread` requires `app` + `instance`.
- ★ `Seed(event_id, app, instance, thread, ts_utc, correlation_id, error_code)`
- ★ `ConfigEntry(app, key, value, raw_ref)` (no change history, D20)
- ★ `AppTopology(app, consumes: [(topic, group)], produces: [topic], databases: [name], limits: {key: value})`
- ★ `FetchStep(order, component, target, argv, reason, direction: seed|upstream|downstream)`, `FetchPlan(steps, done, stop_reason)`
- ★ `CoverageGap(component, target, reason: access_denied | auth_required | missing_input | not_found | empty)` (`missing_input`: D22, added to code in M3)
- ★ `LinkKind` gains `THREAD_LOCAL`.
- `CorrelationGroup`, `TimelineEntry` (`event_id`, `ts_utc`), `Finding`, `Hypothesis`, `ConfidenceFactor`: unchanged. (`SkewEstimate` removed, D30.)
- `AnalysisBundle`: ★ plus `seed`, `topology`, `coverage_gaps`, `traversal`; ★ **minus `parse_issues`** (Q1).
- `IncidentReport` (M9): unchanged sections; timeline/evidence rows also show `app/instance/thread`.

**Confidence factors (★):**
- `id_linkage`: exact vs thread-local vs weak;
- `traversal_coverage`: steps completed vs denied/missing;
- `temporal_precedence`;
- `competing_hypotheses`.

`data_quality` is removed (Q1).

## 4. Scenarios (seed-driven)

Generic names (D6): `edge-gateway`, `order-api`, `fulfillment-worker`, `notification-worker`, `partner-pricing` (★ now an upstream **app** that publishes to Kafka, D13), topic `orders.events`, group `fulfillment-consumers`, DB `appdb`. ★ Scenario 1's upstream topic: `pricing.events` (confirmed; further topic names may be invented generically).

| # | Seed (agent's first message) | What the traversal should surface (generator ground truth; never visible to `investigator`) |
|---|---|---|
| 1 upstream-timeout | `order-api` ERROR: timed out waiting for the pricing event for an order | Config: `order-api` consumes `pricing.events`. Headers lead upstream to `partner-pricing`, whose logs (same correlation ID + thread segment) show Kafka producer timeouts and retries. Producer delivery failures on `pricing.events`. Downstream: `fulfillment-worker` never receives the order on `orders.events` |
| 2 db-config | `fulfillment-worker` ERROR: DB call failed | Config: DB statement timeout far below normal query durations / pool size below worker concurrency (`config.inconsistent`). DB logs show statement timeouts / too many connections from that app |
| 3 consumer-processing (D29; lag deferred) | a downstream app ERROR: entity not found (a downstream symptom) | Upstream (per the seed config) to the consuming app: repeated processing failures and retries on one offset (poison message), visible in consumer client logs; no message on the outgoing topic for that business key |
| 4 ambiguous | an ERROR with **no correlation ID** | Config access denied; scattered SYMPTOMs; no ID chain → **INSUFFICIENT** |

*As implemented in M8 (`src/mocklogs/scenarios/`):*
- *2 `db-config`: seed `fulfillment-worker` DB call failed; config `db.pool.size=4` < `worker.threads=16`; DB `FATAL: too many clients` ×8.*
- *3 `consumer-processing`: seed `notification-worker` timed out waiting for a fulfillment event; `fulfillment-worker` fails 5× on `orders.events-1@5502` (poison payload); the follow-up event is never published.*
- *4 `ambiguous`: seed `edge-gateway` 502 with no correlation ID and no business key; seed config always denied; unrelated retry, leader election, rebalance and slow query.*

Knobs (D8): `seed`, `service_names` (apps, topics, groups, threads, instances), `t0`, `drop_rate`, `dup_rate`, `shuffle`, `malformed_rate`, `access_denied`.

## 5. SKILL.md outline

Built in stages (user decision 2026-10-10): **v0 in M2** (sections 1, 3, 4, 5 + auth), **v1 in M5** (section 2 traversal + 6), **v2 in M10** (sections 7, 8). Each version gets a SKILL_CHANGELOG entry.

**Restructured 2026-10-10 (user decision):** one skill per component (`incident-app-logs`, `incident-app-config`, `incident-kafka`, `incident-db-logs`). Each covers logging in (user SSO), where its inputs come from, commands to search by time/cluster/topic etc., output format, and what to look for. `incident-logs` stays as a slim **coordinator** (hard rules, order, which skill per step). In M10 each component skill gets its own JSON allowlist block, and `allowlist.py` merges them. The subagent (M13) lists all five skills.

**The exact command syntax now lives in the component skills, which supersede item 3 below.** Additions made in v0, pending user review:
- `--save-dir <workdir>` on every fetch command, so output is saved without shell redirects (which the allowlist forbids). This works the same in both agent paths.
- `--since-time`/`--until-time` (real `kubectl` flag names) instead of `--since=<dur>`, because scenario time is fixed in the past and relative durations would drift.
- Mock-only extensions, labeled in the skill:
  - `--grep` (the real tools would be piped to grep);
  - `kafka-consumer-groups --samples N` (stands in for repeated polling, so growing lag is visible);
  - `--describe --all-groups` for downstream discovery.
- Refusal exit codes: 3 = SSO expired/missing, 4 = Forbidden. On SSO expiry, the agent asks the user and retries once.
- Kafka **client** (producer/consumer) activity also appears in the owning app's logs under a Kafka-client logger.
- Added in the per-component restructure, pending review:
  - **Cluster** dimension:
    - app logs/config use `--context <cluster> -n <namespace>`, taken from the seed line, which now carries `cluster` + `namespace` (Kubernetes metadata);
    - Kafka uses `--bootstrap-server` from config `kafka.bootstrap.servers`;
    - DB uses `--host`/`--db` from config `db.host`/`db.name`.
  - **Kafka search by time** via `kafka-get-offsets --time <epoch-ms>`, then `kafka-console-consumer --partition --offset` (real tool shapes).
  - **Default time window:** seed `ts` − 10 min to + 2 min, widened once if empty (to be computed by `investigator plan` in v1).
  - **Model follow-up:** `Event` and `Seed` need `cluster` + `namespace`, and thread scoping becomes cluster + app + instance. Not yet in code; proposed for M3, when parsing first produces these fields.

1. Purpose & hard rules:
   - the first message is the seed;
   - never parse raw logs or config yourself;
   - follow `investigator plan`, and skip a step only with a stated reason;
   - cite bundle event IDs only;
   - INSUFFICIENT is a valid answer.
2. Traversal order (§1), the 1-hop limit, and stop conditions.
   - Auth (D21): all fetch commands use the user's SSO session. On an `SSO session expired or missing` message, stop and ask the user to run `mocklogs sso login`. Never attempt a login.
   - `sso login` is deliberately absent from the allowlist.
3. Component → command map (exact syntax):
   - app logs: `mocklogs kubectl logs deploy/<app> -n <ns> --since=<dur> --timestamps [--grep <id>] [--thread <t> --instance <pod>]`
   - app config: `mocklogs kubectl get configmap <app>-config -n <ns> -o json`
   - Kafka:
     - `mocklogs kafka-consumer-groups --describe --group <g>`
     - `mocklogs kafka-console-consumer --topic <t> --grep <id> --property print.headers=true`
     - `mocklogs kafka logs --component producer|broker|consumer --topic <t> --since=<dur>`
   - DB logs: `mocklogs db logs --db <name> --since=<dur> [--grep <app>]`
   - deterministic: `investigator plan --workdir <dir>`, `investigator correlate --workdir <dir> --json`
4. Output format per command, with annotated samples (MOCK banner, ACCESS DENIED message, SSO-expired message).
5. What counts as an error per component: a pointer to §2. The code classifies; the agent doesn't.
6. Reading the bundle: seed, traversal, coverage gaps, findings, hypotheses, cap.
7. Report contract: required sections, citations, confidence ≤ cap.
8. Allowlist: fenced JSON (D1), one entry per command shape above.

## 6. Technical risks & assumptions

| # | Risk / assumption | Mitigation |
|---|---|---|
| R1 | Python 3.9 target (D1). | JSON allowlist; 3.9 rules in CLAUDE.md; `.venv` (R11, resolved). |
| R2 | Subagent frontmatter `skills:` syntax depends on the Claude Code version. | Verify against current docs in M13. |
| R3 | The subagent's Bash tool can't enforce the allowlist by itself. | PreToolUse hook (D7). |
| R4 | Subagent transcripts live outside `runs/`. | SubagentStop hook copies them; verify early. |
| R5 | Root cause leaking into analysis code. | Boundary test (M1); rules on structure, not names; robustness renames incl. threads/instances. |
| ~~R6/R6b~~ | Skew estimation; a 60 s tolerance blurs cross-source order; delivery delay ≠ skew. | **Withdrawn 2026-10-10 (D30):** clock drift is out of scope; no skew estimation or tolerance |
| R7 | LLM overclaiming. | Validator + cap + 3 retries (D12). |
| R8–R10 | urllib provider; nondeterministic real runs; synthetic data resembling the employer's. | Mocked-transport tests; fake LLM in tests; generic names + user review in M2. |
| R12 | Thread reuse creates false links. | App+instance scope, 1-min window, stop at a different correlation ID, `THREAD_LOCAL` label; a test interleaves two requests on one thread. |
| ★ R13 | ~~Find upstream producers via message headers~~ **Superseded by D26:** related apps and client IDs come from the seed app's config. Headers only attribute individual messages; a header/config mismatch is reported, not resolved by guessing. | Config access denied → step 4 is `missing_input` |
| R14 | Traversal fan-out. | Exactly 1 hop each way (D15); dedupe fetch targets; turn budget. |
| R15 | Error rules are judgment calls. | One table per component, unit-tested, configurable thresholds, user review in M4. |
| R16 | Seed without a correlation ID. | Thread segment + time window only; links labeled weak; cap ≤ LOW. |
| ★ R17 | The seed reaches the planner as text. In the subagent path it must get from the chat into `seed.log` without the LLM re-typing or parsing it. | Python loop: the runtime writes `seed.log`. Subagent: an allowlisted `investigator seed --workdir <dir>` reading stdin, or the user passes it as a file. Decide in M10/M13 (approach confirmed by the user). |
| ★ R18 | Without change history, a "bad config" can only be found from inconsistencies against observed behavior, not from when it changed. | Accepted (D20). Scenario 2 is built on `config.inconsistent`. |
| ★ R19 | The agent acts under the **user's identity** (SSO, D21). Anything it runs is attributed to the user, and an expired session interrupts a run midway. | The allowlist contains read-only commands only; `sso login` is excluded so only the user can authenticate. On expiry: stop, ask the user, and record `auth_required` if they decline. The session marker is never logged (test-enforced). |
| ★ R20 | **Answer leakage to the agent:** the scenario name (e.g. `upstream-timeout`) or scenario-specific examples in SKILL.md would hint at the root cause. | Scenario selection is set by the harness/user (env var), never shown in output or banners, and not available to agent commands. SKILL.md examples are neutral, enforced by `test_skill_neutrality.py`. |
| ★ R22 | **Business keys aren't request-unique.** A `product_id` (and an `order_id` across retries or amendments) matches many unrelated records. | Business-key matches are always bounded by the incident time window. `investigator` labels them `BUSINESS_KEY` links, weaker than an in-app `correlation_id` match, and reports how many distinct requests matched |
| ★ R23 | Plain-text log lines (DB, log4j) can't show that they were truncated, so a cut line parses as a valid event with a partial message. Log4j lines are protected by their trailing `(logger)` pattern; DB lines aren't. | Accepted: the event is still exactly what the log says (a prefix of the real line), never invented content. A test enforces the prefix property. Detectors must not rely on a message's *ending* |
| ★ R24 | Single-snapshot lag rows (`--all-groups`, `--samples 1`) carry no timestamp, because the real tool prints none, so they can't be placed on the timeline. | `--samples N` rows are timed. Untimed rows are used for topology (who consumes what), not chronology |
| ~~★ R25~~ | **Which clock is right is unknowable.** Skew between two clocks can be measured (same occurrence on both), but only as a relative offset. | **Withdrawn 2026-10-10 (D30):** no skew measurement, so no reference clock |
| ~~★ R26~~ | Design §R6 said "causal order inside an ID chain overrides timestamps". **Not implemented in M6:** ordering is by skew-adjusted time only. | **Withdrawn 2026-10-10 (D30):** no clock correction, so causal reordering isn't needed |
| ~~R21~~ | **Withdrawn 2026-10-10.** Assuming related apps run in the seed's cluster is a guess, which D22 forbids. Related apps need their own `app[<name>]:` line in the incident; otherwise `missing_input`. | — |

## 7. Milestone plan

Detailed, editable version with kickoff prompts: `docs/design/MILESTONES.md`.

| M | Scope |
|---|---|
| M0 ✅ | Process + design Rev 1; Rev 2 merged, awaiting final approval |
| M1 ✅ | Skeleton + models (Rev 2) |
| M2 | **SKILL.md v0 first** (commands, connection/SSO, formats), then `mocklogs`: 4 components, SSO, access control, scenario 1 |
| M3 | Parsing + normalization (incl. app/instance/thread) + dedupe |
| M4 | Per-component error classification (§2); user reviews the rule tables |
| M5 | Config → topology + `investigator plan`; **SKILL.md v1** (traversal: upstream via headers, downstream via consumer groups) |
| M6 | Correlation (IDs + thread segments) + timeline |
| M7 | Detectors + `investigator correlate` → bundle |
| M8 | Scenarios 2–4 + robustness matrix |
| M9 | Report model + validator + Markdown |
| M10 | **SKILL.md v2** (JSON allowlist + report contract) + command runner |
| M11 | Provider interface, fake LLM, tool loop, transcripts |
| M12 | Anthropic provider + replay (needs API key) |
| M13 | Claude Code subagent + hook + transcript capture |
| M14 | README + demo |

## 8. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Python version | Resolved: 3.9; JSON allowlist |
| D2 | ~~Skew tolerance~~ | **Superseded by D30:** no clock-skew tolerance or handling |
| D3 | Offline demo | Resolved: replay transcripts from `runs/` |
| D4 | Report output | Resolved: JSON → Markdown |
| D5 | Mock formats | Resolved, ★ amended: app logs JSON lines incl. `instance`, `thread`; Kafka/DB native-style text; app config as `kubectl get configmap -o json` |
| D6 | Generic names | Resolved (§4), ★ plus `pricing.events` (confirmed). The AI may invent further generic topic names as needed (user: "make up the topic names") |
| D7 | Subagent allowlist enforcement | Resolved: PreToolUse hook |
| D8 | Scenario data | Resolved: seeded generators + knobs + snapshots |
| D9 | Packaging | Resolved: pyproject + setuptools backend |
| D10 | Model / key | Resolved: `claude-sonnet-5-5`, `ANTHROPIC_API_KEY` (key later) |
| D11 | Push cadence | Resolved: after each approved milestone |
| D12 | Validator retries | Resolved: 3, then INSUFFICIENT |
| Q1 | Data-quality issues | ★ Resolved: not needed. Removed from the bundle and confidence factors; parsers still skip malformed lines safely |
| D13 | `partner-pricing` | ★ Resolved: an upstream app that publishes to Kafka; no HTTP upstream source |
| D14 | DB server config | ★ Resolved: dropped; DB settings come from the app config |
| D15 | Traversal depth | ★ Resolved: exactly one hop upstream and one hop downstream |
| D16 | Access model | ★ Resolved: mock access list; denied → coverage gap → lower cap |
| D17 | Thread segment | ★ Resolved: 1-minute window for app logs, stopping early at a different correlation ID (both confirmed) |
| D18 | Traversal planning | ★ Resolved: deterministic `investigator plan`. **Amended by D31:** its output is now suggestions; the agent may deviate, with every command checked |
| D19 | Seed input | ★ Resolved: the app log line is the agent's first message |
| D20 | Config change history | ★ Resolved: not used |
| D21 | Authentication | ★ Resolved 2026-10-10 (user): the **user's SSO session** for **all four components** (first stated for Kafka, extended to app logs, config and DB logs on confirmation); no agent credentials exist. Design in §1.2 |
| D22 | Required inputs | ★ Resolved 2026-10-10 (user): **no input, no access**. Each skill lists its required inputs; if any is missing, none of that skill's commands run, and a `missing_input` gap is recorded |
| D23 | Incident message | ★ Resolved 2026-10-10 (user approved the skills as written: "the skills are fine now"): `INCIDENT` / `seed:` / `app:` (seed app only) / `app[<name>]:` (per related app) / `kafka: bootstrap= topics= [group=]` / `db: host= name=`. The config may supply topic direction (consume vs. produce) and the consumer group when the incident gives none |
| D24 | Safeguards & rate limiting | ★ Deferred 2026-10-10: the **user** will add these later. Not in any milestone's scope until then |
| D25 | Correlation keys | ★ Resolved 2026-10-10 (user): `correlation_id` = in-app only; cross-service = business key by seed source class: `Order*` → `order_id`, `Product*` → `product_id` (stored as `order_id`/`product_id` in Kafka values and DB statements). The user will supply more rules. Design §1.0 |
| D25a | Order/Product services | ★ Resolved 2026-10-10 (user): orders come from the **OrderService**, product-based inputs from the **ProductService**. Each logs `order_id`/`product_id` with its own in-app correlation ID, consistent within the service. Mock amended (D6): seed app `order-api` → `order-service`, upstream `partner-pricing` → `product-service`, with `Order*`/`Product*` source classes. Older references to the old names in this document are historical |
| D25b | Correlation-key list | ★ Resolved 2026-10-10 (user: "For demo this is fine"): the table stays at `Order*` → `order_id`, `Product*` → `product_id` for the demo |
| D26 | Kafka client ↔ app mapping | ★ Resolved 2026-10-10 (user): never map by name/prefix. The seed app's configmap declares its upstream/downstream apps and their Kafka client IDs (`upstream.apps`, `downstream.apps`, `upstream.<app>.kafka.client.ids`, `downstream.<app>.kafka.client.ids`, own `kafka.*.client.id`). That is the **only** source for step-4 targets and for attributing `clientId=` / `CLIENT-ID` to apps. No config → related apps unknown (`missing_input`). The `producer_app` header only attributes a single message |
| D27 | Where vs. who | ★ Resolved 2026-10-10 (user: "This is correct"): the **incident** is the only source of *where* to look (clusters, namespaces, Kafka bootstrap/topics, DB host/name). The seed **config** only says *who* is related (upstream/downstream apps, their Kafka client IDs) and gives limits/topic direction. Config values for clusters/DBs are never used for access; a mismatch with the incident is reported |
| D28 | Collect first; Kafka collection scope | ★ Resolved 2026-10-10 (user): the agent's job is to **collect** all related records; assessment comes later. Kafka collection per incident topic = **incoming** + **outgoing** messages (business key), **retry** logs, and any **topic error / connection timeout**. Nothing else (consumer-group lag and all-groups are dropped from the skill; `mocklogs` still supports them). Scenario 3 impact resolved by D29 |
| D29 | Consumer lag | ★ Deferred 2026-10-10 (user: "we can add lag later"). Until then, scenario 3 is a **consumer processing failure with retries** (a poison message retried on one offset → downstream symptoms), observable through the D28 collections: consumer client logs with retries/errors, and incoming/outgoing messages. Lag collection is a later addition; `mocklogs` keeps the `kafka-consumer-groups` command and the M4 lag rules stay in code, unused by the skill |
| D30 | Clock drift | ★ Resolved 2026-10-10 (user): "the clock drift between machines is not an issue, since the window is big. Ignore all the references in the application that measure or take into account clock drift/skew". Events are ordered by their own UTC timestamps; skew estimation, correction, tolerance, uncertainty flags and the mock skew knob are removed. Supersedes D2; withdraws R6/R6b/R25/R26 |
| D31 | AI as investigator, code as guardrail | ★ Resolved 2026-10-10 (user: "AI should do the investigations but not be a just the narraotr"; "Yes that makes sense continue"). (1) `investigator plan` becomes **suggestions**; the agent investigates freely, and every command must pass `investigator check` (inputs only from the incident/seed config: D22/D26/D27). (2) Detector hypotheses are **leads**; the AI may propose any bundle event as the cause, scored by `investigator score --cause` with the same factor/ceiling code, and may claim at most that ceiling. (3) The AI drives the loop: collect → correlate → decide what's missing → fetch more (checked) → re-correlate → conclude or INSUFFICIENT with the access/inputs needed. (4) The AI may interpret unclassified errors, labeled "AI interpretation", never raising the ceiling alone. Code keeps parsing, linking, timeline, rule labels (as evidence features), confidence math and citation checks |
