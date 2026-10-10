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
   (IDs + thread segments) → timeline (skew-tolerant) → detectors
   → hypotheses + confidence cap → ANALYSIS BUNDLE (JSON)
   │
   ▼
 LLM reasons over the bundle only ─► submit_report ─► validator
   (event IDs must exist, confidence ≤ cap, 3 retries then INSUFFICIENT)
   ─► report.json + report.md; transcript ─► runs/<ts>-<scenario>.jsonl
```

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
    timeline.py                # skew estimation, 60 s tolerance (D2), uncertainty flags
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
- ★ `CoverageGap(component, target, reason: access_denied | auth_required | not_found | empty)`
- ★ `LinkKind` gains `THREAD_LOCAL`.
- `CorrelationGroup`, `TimelineEntry`, `SkewEstimate`, `Finding`, `Hypothesis`, `ConfidenceFactor`: unchanged.
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
| 3 consumer-lag | `notification-worker` ERROR: entity not found (a downstream symptom) | Upstream via headers to `fulfillment-worker`: repeated processing failures on one offset (poison message), lag growing on one partition |
| 4 ambiguous | an ERROR with **no correlation ID** | Config access denied; scattered SYMPTOMs; no ID chain → **INSUFFICIENT** |

Knobs (D8): `seed`, `service_names` (apps, topics, groups, threads, instances), `t0`, `per_source_skew_ms`, `drop_rate`, `dup_rate`, `shuffle`, `malformed_rate`, `access_denied`.

## 5. SKILL.md outline

Built in stages (user decision 2026-10-10): **v0 in M2** (sections 1, 3, 4, 5 + auth), **v1 in M5** (section 2 traversal + 6), **v2 in M10** (sections 7, 8). Each version gets a SKILL_CHANGELOG entry.

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
| R6/R6b | Skew estimation; a 60 s tolerance blurs cross-source order; delivery delay ≠ skew. | Causal order inside ID chains wins; order-uncertain count reported; lag is its own signal. |
| R7 | LLM overclaiming. | Validator + cap + 3 retries (D12). |
| R8–R10 | urllib provider; nondeterministic real runs; synthetic data resembling the employer's. | Mocked-transport tests; fake LLM in tests; generic names + user review in M2. |
| R12 | Thread reuse creates false links. | App+instance scope, 1-min window, stop at a different correlation ID, `THREAD_LOCAL` label; a test interleaves two requests on one thread. |
| R13 | Real Kafka doesn't list a topic's producers. | Message headers carry the producing app + correlation ID. A missing header becomes a coverage gap, never a guess. |
| R14 | Traversal fan-out. | Exactly 1 hop each way (D15); dedupe fetch targets; turn budget. |
| R15 | Error rules are judgment calls. | One table per component, unit-tested, configurable thresholds, user review in M4. |
| R16 | Seed without a correlation ID. | Thread segment + time window only; links labeled weak; cap ≤ LOW. |
| ★ R17 | The seed reaches the planner as text. In the subagent path it must get from the chat into `seed.log` without the LLM re-typing or parsing it. | Python loop: the runtime writes `seed.log`. Subagent: an allowlisted `investigator seed --workdir <dir>` reading stdin, or the user passes it as a file. Decide in M10/M13 (approach confirmed by the user). |
| ★ R18 | Without change history, a "bad config" can only be found from inconsistencies against observed behavior, not from when it changed. | Accepted (D20). Scenario 2 is built on `config.inconsistent`. |
| ★ R19 | The agent acts under the **user's identity** (SSO, D21). Anything it runs is attributed to the user, and an expired session interrupts a run midway. | The allowlist contains read-only commands only; `sso login` is excluded so only the user can authenticate. On expiry: stop, ask the user, and record `auth_required` if they decline. The session marker is never logged (test-enforced). |

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
| D2 | Skew tolerance | Resolved: 60 000 ms, configurable, tune later |
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
| D18 | Traversal planning | ★ Resolved: deterministic `investigator plan` |
| D19 | Seed input | ★ Resolved: the app log line is the agent's first message |
| D20 | Config change history | ★ Resolved: not used |
| D21 | Authentication | ★ Resolved 2026-10-10 (user): the **user's SSO session** for **all four components** (first stated for Kafka, extended to app logs, config and DB logs on confirmation); no agent credentials exist. Design in §1.2 |
