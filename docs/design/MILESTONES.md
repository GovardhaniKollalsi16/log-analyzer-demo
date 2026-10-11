# Milestone Plan (Rev 2, detailed, editable)

Matches `PROPOSAL.md` Rev 2. **The user reviews and edits this file.** Each milestone lists its scope, tests, "done when", and a **kickoff prompt** to modify and send. Every milestone ends with real test output, a stop for review, and a push after approval (D11).

Status: ✅ approved · 🟡 implemented, awaiting review · ⬜ not started

**Deferred, owned by the user (D24):** safeguards and rate limiting, to be added later. Not in any milestone until the user schedules them.
**Deferred (D29):** consumer-lag collection, to be added later.

---

## M0 — Process + design ✅ (Rev 2 approved 2026-10-10)
CLAUDE.md, docs/process/*, PROPOSAL Rev 1 (pushed) → Rev 2 (seed-driven traversal, per-component errors), decisions D1–D20 + Q1, `.venv`.

## M1 — Skeleton + models ✅ (approved and pushed 2026-10-10)
Done: `pyproject.toml`, packages, `models.py`, 11 tests incl. the boundary guard.
**Pending after Rev 2 approval:** apply PROPOSAL §3.1:
- `Source` loses `UPSTREAM`, gains `APP_CONFIG`;
- new `Severity`, `KafkaRef`, `Seed`, `ConfigEntry`, `AppTopology`, `FetchStep`/`FetchPlan`, `CoverageGap`;
- `LinkKind.THREAD_LOCAL`;
- `Event` gains app/instance/thread/severity/error_code/kafka;
- the bundle drops `parse_issues`;
- tests updated.

> **Kickoff prompt:** "Rev 2 approved. Update M1 models to PROPOSAL §3.1 and rerun the tests."

---

## M2 — SKILL.md v0, then `mocklogs`: 4 components + SSO + access control + scenario 1 ✅ (approved and pushed 2026-10-10)
**Step 1, skills first (user decisions 2026-10-10):** write the skills as **one per component** (`incident-app-logs`, `incident-app-config`, `incident-kafka`, `incident-db-logs`) plus the `incident-logs` coordinator. It is the agent-facing contract for every `mocklogs` command: how to connect to each component (SSO, access), exact syntax, output formats, and how to handle refusals. **The user reviews v0 before any `mocklogs` code.** After `mocklogs` exists, the illustrative samples in v0 are replaced with real generated output (SKILL_CHANGELOG entry).

**Step 2 scope**
- `mocklogs/scenarios/base.py`: a `ScenarioKnobs` dataclass and a generator interface returning per-component raw data **plus the seed line**.
- `scenarios/upstream_timeout.py` (scenario 1: `partner-pricing` producer timeouts on `pricing.events` → `order-api` waits time out).
- `render.py`:
  - app logs as JSON lines with `app`, `instance`, `thread`, `correlation_id`;
  - configmap JSON;
  - Kafka producer/broker/consumer text;
  - `kafka-consumer-groups --describe` table;
  - `kafka-console-consumer` with headers;
  - DB log text.
- `access.py`: a mock access list; denied → `Error from server (Forbidden): ... MOCK` style output.
- `sso.py` (D21): `mocklogs sso login` (run by the **user** only) writes a mock session with an expiry. All fetch commands (app logs, config, Kafka, DB logs) require a valid session; otherwise they print the SSO-expired message and exit non-zero. Tests: missing/expired session → message + non-zero exit; the session marker never appears in any output.
- `cli.py`: the commands in PROPOSAL §5. Every output starts with a MOCK banner. Register the `mocklogs` console script.

**Tests:** golden snapshots per command (seeded); MOCK banner everywhere; same seed gives identical output; knobs change output; access denial.

**Done when:** tests green and **the user reviews a sample of every command's output**, including how closely it looks like real tools and any resemblance to the employer's systems.

> **Kickoff prompt:** "Start M2 per MILESTONES.md. Show me SKILL.md v0 first; then show me one sample of each command's output before writing snapshot tests."

---

## M3 — Parsing + normalization + dedupe ✅ (approved and pushed 2026-10-10)
**Scope**
- **Model follow-up (from the per-component skills):** add `cluster` + `namespace` to `Event` and `Seed`; thread links scoped by cluster + app + instance.
- **Model follow-up (D25):** `Event.keys: Dict[str, str]` for business keys (`order_id`, `product_id`, …); `LinkKind.BUSINESS_KEY`; `Seed.business_key`; correlation groups key on `(app, correlation_id)` within an app, and on the business key across apps.
- **Model follow-up (D22/D23):** `GapReason.MISSING_INPUT`; an `Incident` model (seed line + per-source inputs) parsed deterministically from the agent's first message.
- `adapters/` with a `LogSource` protocol and a `FileSource` for tests.
- `parsing/`: one parser per format. Malformed lines are skipped and never crash (Q1: not surfaced in the bundle).
- `normalize.py`: UTC (incl. `Z`, offsets, epoch ms), levels, IDs from fields/headers/text, app/instance/thread, stable `event_id`.
- `dedupe.py`.

**Tests:** malformed/truncated lines skipped; mixed time zones; duplicates collapsed; stable IDs; out-of-order input.

> **Kickoff prompt:** "Start M3 per MILESTONES.md."

---

## M4 — Per-component error classification ✅ (approved and pushed 2026-10-10)
**Status:** step 1 done: rule tables as code in `src/investigator/classify/` (commit `4716293`). **Step 2 (after approval):** one matching and one non-matching test per rule, lag/config cases, a rename-invariance test, then push.
**Scope:** `classify/app.py`, `config.py`, `kafka.py`, `db.py` implementing PROPOSAL §2. Each rule sets `severity` + `error_code`, with thresholds in one config object.

**Tests:** one positive and one negative fixture per rule; renamed apps/topics classify identically.

**Done when:** the user has **reviewed the rule tables (as code) before** M5+ depend on them.

> **Kickoff prompt:** "Start M4 per MILESTONES.md. Show me the rule tables for review before writing tests."

---

## M5 — Config → topology + `investigator plan` ✅ (approved "for now" and pushed 2026-10-10)
**Scope**
- `config_model.py`: configmap JSON → `ConfigEntry`s + `AppTopology`, including (D26) `upstream.apps` / `downstream.apps` and a **client-ID → app map** built only from the declared `*.kafka.client.ids` + own `kafka.*.client.id`. Used to attribute Kafka log lines and lag rows; unmapped IDs stay unattributed.
- `planner.py`: the **incident** (seed + per-source inputs) + fetched outputs in the workdir → `FetchPlan` following PROPOSAL §1. **No input, no access (D22):** a step with a missing required input becomes a `missing_input` gap, never a guessed command:
  - seed app logs → config → Kafka (per incident topic: incoming + outgoing messages by business key, producer/consumer/broker logs for retries, errors and timeouts; D28) → 1 hop up/down → DB;
  - access-denied targets become `CoverageGap`s.
- `investigator plan --workdir <dir>` prints the next allowlisted argv lists as JSON. Register the `investigator` console script.
- **SKILL.md v1:** the traversal section. Related apps come **only** from the seed config's `upstream.apps` / `downstream.apps` (D26). *Where* to look comes **only** from the incident (D27). It also covers the 1-hop rule and how to follow `investigator plan`. Logged in SKILL_CHANGELOG.

**Tests:** plan sequence for scenario 1 step by step; config access denied → related apps unknown → step 4 recorded as `missing_input`; no `db:` line in the incident → no DB step (`missing_input`); a related app without an `app[<name>]:` line is skipped; never more than 1 hop; unmapped client IDs stay unattributed.

> **Kickoff prompt:** "Start M5 per MILESTONES.md. Walk me through the plan output for scenario 1 step by step."

---

## M6 — Correlation (IDs + thread segments) + timeline ✅ (approved and pushed 2026-10-10)
**Scope**
- `correlation.py`: links, each labeled with its kind and strength:
  - `EXACT_ID`: same app + same in-app `correlation_id` (D25: never across apps);
  - `BUSINESS_KEY`: same `order_id`/`product_id` across apps, Kafka messages and DB statements, bounded by the incident window (R22);
  - `THREAD_LOCAL`: cluster + app + instance + thread, 1-min window, stops at a different correlation ID (D17);
  - **resource links:** Kafka broker/producer lines ↔ app errors naming the same topic-partition;
  - **cross-source copies:** the same Kafka client line seen in an app's logs and in `kafka logs` is linked as one occurrence, so detectors don't double-count (found in M4);
  - Kafka client IDs attributed to apps via the M5 config map (D26).
- **Planner addition (found by the M6 timeline demo):** each app's Kafka client lines are fetched by the client IDs the seed config declares. They carry no business key or correlation ID, but they hold the app-side retries and timeouts (and are linked to their `kafka logs` copies so nothing is counted twice).
- `timeline.py`: chronological order by UTC timestamp, deterministic ties (D30: no clock-drift handling).

**Tests:** two requests interleaved on one thread are not merged; the same thread name in two apps is not linked; correlation IDs never link across apps; a business key outside the window doesn't link; cross-source copies collapse to one occurrence; shuffled input gives the same timeline.

> **Kickoff prompt:** "Start M6 per MILESTONES.md. Show me the scenario 1 timeline."

---

## M7 — Detectors + `investigator correlate` ✅ (approved and pushed 2026-10-10)
**Scope**
- `detectors/`: cross-record patterns over classified events:
  - retry amplification
  - producer delivery failure chain
  - lag growth / stuck partition
  - poison message (repeated failure on one offset)
  - DB error burst
  - config inconsistency confirmed by observed behavior (cross-source config checks moved here from M4: a timeout vs. observed latencies, a topic missing from Kafka, a DB never seen)
  - *proposed, pending user OK:* an app exception followed by a later success for the same correlation ID is downgraded to SYMPTOM ("transient")
  - first error per app
- `analysis.py`: hypotheses, the confidence factors (`id_linkage`, `traversal_coverage`, `temporal_precedence`, `competing_hypotheses`), the cap, and the bundle.
- `investigator correlate --workdir <dir> --json`.

**Tests:** each detector positive/negative; scenario 1 bundle snapshot; cap rules.

> **Kickoff prompt:** "Start M7 per MILESTONES.md. List the confidence-cap rules for my approval before coding them."

---

## M8 — Scenarios 2–4 + robustness matrix 🟡 (in progress; unaffected by D31)
**Scope:** db-config, consumer-processing-failure (D29: lag deferred; observable via consumer retries/errors and missing outgoing messages), and ambiguous generators. `tests/robustness/` covers every scenario × each of:
- rename apps/topics/groups/threads/instances;
- shift times;
- shuffle;
- drop non-critical records;
- duplicates;
- malformed lines;
- access denial (where applicable).

**Done when:** the matrix is green and the user reviews scenario 2–4 samples.

> **Kickoff prompt:** "Start M8 per MILESTONES.md."

---

## M8b — Guardrail commands for an investigating AI (D31) ⬜
**Scope:**
- `investigator check --workdir <dir> -- <argv…>`: allow/deny one proposed command. Clusters, namespaces, apps, topics, groups, hosts and DBs must come from the incident (where) or the seed config (who); the command shape must be one the skills document. Deny reasons are machine-readable.
- `investigator score --workdir <dir> --cause <event_id>`: the four factors and the ceiling for any bundle event the AI proposes as the cause (the M7 code, exposed for one event).

**Tests:** allowed vs. denied commands (unknown cluster/topic/app, undeclared related app, a DB not in the incident); score for a detector cause equals the bundle's; score for an unrelated event is LOW/INSUFFICIENT; unknown event ID rejected.

> **Kickoff prompt:** "Start M8b per MILESTONES.md."

---

## M9 — Report model + validator + Markdown ⬜
- **D31:** the report may name an AI-proposed cause; the validator checks it exists in the bundle and that the claimed confidence ≤ its `investigator score` ceiling. AI interpretations of unclassified errors are labeled and never raise confidence.

**Scope:**
- `IncidentReport` with all required sections;
- a validator rejecting unknown event IDs, confidence > cap, a root cause without evidence, missing sections, and HIGH/MEDIUM with an `unknown` root cause;
- JSON → Markdown.

**Tests:** one rejection test per rule; valid report round-trips.

> **Kickoff prompt:** "Start M9 per MILESTONES.md."

---

## M10 — SKILL.md v2 (allowlist) + command runner ⬜
**Scope:**
- **Skills v2:** a fenced JSON allowlist block **in each component skill**, merged by `allowlist.py`; the report contract in the coordinator;
- **D31:** coordinator §6 rewritten from "run the planner's steps exactly" to "start from the suggestions, investigate; every command goes through `investigator check`; record why";
- `allowlist.py`;
- `MockCliSource` (subprocess argv, no shell);
- resolve R17 (getting the seed into `seed.log`);
- `sso login` excluded from the allowlist, with a test (D21);
- SKILL_CHANGELOG entry for v2.

**Tests:** allowed vs. rejected commands (pipes, `;`, `$(...)`, unknown flags); every SKILL.md example is allowlisted.

> **Kickoff prompt:** "Start M10 per MILESTONES.md. Show me the SKILL.md v2 diff before wiring it in."

---

## M11 — Provider interface, fake LLM, tool loop, transcripts ⬜
**Scope:**
- `LLMProvider` + `ScriptedFakeLLM`;
- tools `run_command` (always via `investigator check`), `plan` (suggestions), `correlate`, `score`, `submit_report` (D31);
- the loop takes the seed as its first message, writes `seed.log`, uses a turn budget, and retries up to 3 times (D12) before INSUFFICIENT;
- `narration.py`;
- `runs/<ts>-<scenario>.jsonl`.

**Tests:** end-to-end for all 4 scenarios with the fake LLM; bogus-citation retry; fail-closed after 3; transcript complete.

> **Kickoff prompt:** "Start M11 per MILESTONES.md."

---

## M12 — Anthropic provider + replay ⬜ (needs `ANTHROPIC_API_KEY`)
**Scope:**
- urllib provider (`claude-sonnet-5-5`, key from env only);
- `investigator replay runs/<file>.jsonl` (D3).

**Tests:** mocked transport; replay reproduces the report.

**Manual step:** one real run per scenario saved to `runs/`.

> **Kickoff prompt:** "Start M12 per MILESTONES.md. I've exported ANTHROPIC_API_KEY."

---

## M13 — Claude Code subagent + hook + transcripts ⬜
**Scope:**
- `.claude/agents/incident-investigator.md` listing all five skills (`incident-logs`, `incident-app-logs`, `incident-app-config`, `incident-kafka`, `incident-db-logs`) in its frontmatter (verify the syntax first, R2);
- the allowlist PreToolUse hook;
- transcript capture into `runs/`;
- SKILL_CHANGELOG entries per run-triggered change.

**Tests:** hook unit tests; a manual subagent run per scenario.

> **Kickoff prompt:** "Start M13 per MILESTONES.md. Verify the frontmatter syntax first and tell me what you found."

---

## M14 — README + demo ⬜
README (synthetic-data disclaimer, architecture, traversal, error definitions, how to run both paths, how to read a report), `demo.sh` (offline replay of all 4), and a clean-checkout walkthrough.

> **Kickoff prompt:** "Start M14 per MILESTONES.md."
