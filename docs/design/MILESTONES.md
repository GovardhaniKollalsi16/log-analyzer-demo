# Milestone Plan (Rev 2, detailed, editable)

Matches `PROPOSAL.md` Rev 2. **The user reviews and edits this file.** Each milestone lists its scope, tests, "done when", and a **kickoff prompt** to modify and send. Every milestone ends with real test output, a stop for review, and a push after approval (D11).

Status: ✅ approved · 🟡 implemented, awaiting review · ⬜ not started

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

## M2 — SKILL.md v0, then `mocklogs`: 4 components + SSO + access control + scenario 1 ⬜
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

## M3 — Parsing + normalization + dedupe ⬜
**Scope**
- **Model follow-up (from the per-component skills):** add `cluster` + `namespace` to `Event` and `Seed`; thread links scoped by cluster + app + instance.
- `adapters/` with a `LogSource` protocol and a `FileSource` for tests.
- `parsing/`: one parser per format. Malformed lines are skipped and never crash (Q1: not surfaced in the bundle).
- `normalize.py`: UTC (incl. `Z`, offsets, epoch ms), levels, IDs from fields/headers/text, app/instance/thread, stable `event_id`.
- `dedupe.py`.

**Tests:** malformed/truncated lines skipped; mixed time zones; duplicates collapsed; stable IDs; out-of-order input.

> **Kickoff prompt:** "Start M3 per MILESTONES.md."

---

## M4 — Per-component error classification ⬜
**Scope:** `classify/app.py`, `config.py`, `kafka.py`, `db.py` implementing PROPOSAL §2. Each rule sets `severity` + `error_code`, with thresholds in one config object.

**Tests:** one positive and one negative fixture per rule; renamed apps/topics classify identically.

**Done when:** the user has **reviewed the rule tables (as code) before** M5+ depend on them.

> **Kickoff prompt:** "Start M4 per MILESTONES.md. Show me the rule tables for review before writing tests."

---

## M5 — Config → topology + `investigator plan` ⬜
**Scope**
- `config_model.py`: configmap JSON → `ConfigEntry`s + `AppTopology`.
- `planner.py`: the seed (`seed.log`) + fetched outputs in the workdir → `FetchPlan` following PROPOSAL §1:
  - seed app logs → config → Kafka → 1 hop up/down → DB;
  - access-denied targets become `CoverageGap`s.
- `investigator plan --workdir <dir>` prints the next allowlisted argv lists as JSON. Register the `investigator` console script.
- **SKILL.md v1:** the traversal section. It explains how upstream apps are found (message headers on consumed topics), how downstream apps are found (consumer groups on produced topics), the 1-hop rule, and how to follow `investigator plan`. Logged in SKILL_CHANGELOG.

**Tests:** plan sequence for scenario 1 step by step; access denied at config → Kafka steps can't be planned → gap recorded; no DB in config → no DB step; never more than 1 hop.

> **Kickoff prompt:** "Start M5 per MILESTONES.md. Walk me through the plan output for scenario 1 step by step."

---

## M6 — Correlation (IDs + thread segments) + timeline ⬜
**Scope**
- `correlation.py`: union-find over IDs, plus `THREAD_LOCAL` segments (app+instance scope, 1-min window, stop at a different correlation ID, D17).
- `timeline.py`: skew estimation from causal pairs; 60 s tolerance (D2); causal order within ID chains wins; `order_uncertain` flags.

**Tests:** two requests interleaved on one thread are not merged; the same thread name in two apps is not linked; shuffled input gives the same timeline; injected skew; delivery delay ≠ skew.

> **Kickoff prompt:** "Start M6 per MILESTONES.md. Show me the scenario 1 timeline with skew injected."

---

## M7 — Detectors + `investigator correlate` ⬜
**Scope**
- `detectors/`: cross-record patterns over classified events:
  - retry amplification
  - producer delivery failure chain
  - lag growth / stuck partition
  - poison message (repeated failure on one offset)
  - DB error burst
  - config inconsistency confirmed by observed behavior
  - first error per app
- `analysis.py`: hypotheses, the confidence factors (`id_linkage`, `traversal_coverage`, `temporal_precedence`, `competing_hypotheses`), the cap, and the bundle.
- `investigator correlate --workdir <dir> --json`.

**Tests:** each detector positive/negative; scenario 1 bundle snapshot; cap rules.

> **Kickoff prompt:** "Start M7 per MILESTONES.md. List the confidence-cap rules for my approval before coding them."

---

## M8 — Scenarios 2–4 + robustness matrix ⬜
**Scope:** db-config, consumer-lag, and ambiguous generators. `tests/robustness/` covers every scenario × each of:
- rename apps/topics/groups/threads/instances;
- shift times;
- shuffle;
- drop non-critical records;
- duplicates;
- skew below tolerance;
- malformed lines;
- access denial (where applicable).

**Done when:** the matrix is green and the user reviews scenario 2–4 samples.

> **Kickoff prompt:** "Start M8 per MILESTONES.md."

---

## M9 — Report model + validator + Markdown ⬜
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
- tools `run_command`, `plan`, `correlate`, `submit_report`;
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
