# Milestone Plan (detailed, editable)

This expands the table in `PROPOSAL.md` §7. **The user reviews and edits this file.** Each milestone has its scope, the deliverables, the tests, "done when", and a **kickoff prompt** the user can modify and send. Every milestone ends with real test output, a stop for review, and a push after approval (D11).

Status key: ✅ approved · 🟡 implemented, awaiting review · ⬜ not started

---

## M0 — Process setup + design ✅
Delivered: CLAUDE.md, docs/process/*, PROPOSAL.md, decisions D1–D12, `.venv`. Pushed.

## M1 — Skeleton, models, pytest wiring 🟡
Delivered: `pyproject.toml`, `investigator`/`mocklogs` packages, `models.py`, 11 tests including the import/vocabulary boundary guard. Not pushed yet.

---

## M2 — `mocklogs` CLI + scenario 1 generator ⬜
**Scope**
- `src/mocklogs/scenarios/base.py`: a `ScenarioKnobs` dataclass (`seed`, `service_names` map, `t0`, `per_source_skew_ms`, `drop_rate`, `dup_rate`, `shuffle`, `malformed_rate`) and a generator interface returning per-source raw lines.
- `src/mocklogs/scenarios/upstream_timeout.py`: scenario 1 (upstream latency → `order-api` timeouts → retries → Kafka producer delivery failures).
- `src/mocklogs/render.py`: per-tool formatting (D5). App logs are JSON lines; upstream access log, Kafka producer/broker/consumer, `kafka-consumer-groups --describe` table, psql-style `SHOW ALL` dump, and DB log are native-style text.
- `src/mocklogs/cli.py`: subcommands `kubectl logs`, `upstream access-log`, `kafka logs`, `kafka-consumer-groups --describe`, `psql -c "SHOW ALL"`, `db logs`. Scenario selected by `--scenario` or `MOCKLOGS_SCENARIO`. Every output starts with a `# MOCK DATA — synthetic, not from any real system` banner.
- Register the `mocklogs` console script.

**Tests:** golden snapshot per command for scenario 1 (seeded); every output has the MOCK banner; the same seed gives identical output and a different seed gives different output; knobs (rename, time shift, drop, dup, shuffle, malformed) visibly change the output.

**Done when:** tests green; **the user reviews sample output of every command** for realism and for any resemblance to the employer's systems.

> **Kickoff prompt:** "Start M2. Build the mocklogs CLI and the scenario 1 generator per MILESTONES.md. Show me one sample of each command's output before writing snapshot tests."

---

## M3 — Parsing + normalization + dedupe ⬜
**Scope**
- `investigator/adapters/`: `LogSource` protocol, plus `FileSource` (reads saved CLI output) for tests. The subprocess-backed `MockCliSource` comes in M8 with the allowlist.
- `investigator/parsing/`: one parser per format (JSON-lines app, access log, Kafka text, consumer-group table, psql config dump, DB log). Each returns `Event`s plus `ParseIssue`s and never raises on a bad line.
- `investigator/normalize.py`: UTC conversion (incl. `Z`, offsets, epoch ms), level mapping, ID extraction from fields/headers/message text, stable `event_id` = hash(source, raw text, occurrence index).
- `investigator/dedupe.py`: collapse exact and near-exact duplicates (same source + ts + normalized message + IDs) and keep all `raw_refs` + `duplicate_count`.

**Tests:** malformed lines become ParseIssues, never crashes; truncated JSON; missing timestamps; mixed time zones; duplicate collapse; event IDs stable across runs and different for distinct lines.

> **Kickoff prompt:** "Start M3: parsers, normalization and dedupe per MILESTONES.md. Include malformed/duplicate fixtures."

---

## M4 — Correlation + timeline with skew tolerance ⬜
**Scope**
- `investigator/correlation.py`: union-find over `correlation_id`/`trace_id`/`message_id`/`request_id` → `CorrelationGroup`s. Events without IDs are left unlinked, or linked `WEAK_TEMPORAL` only under an explicit, labeled rule.
- `investigator/timeline.py`:
  - Per-source skew estimation from causal pairs (produce → broker ack → consume for one `message_id`; request → upstream call).
  - Order by adjusted time, with causal order inside an ID chain overriding timestamps.
  - Events within tolerance (default 60 s, D2) and with no causal link are marked `order_uncertain`.
  - Report the count of uncertain events (R6b).

**Tests:** shuffled input → identical timeline; injected skew → corrected or flagged, never silently mis-ordered; missing IDs; a Kafka delivery delay is not mistaken for skew.

> **Kickoff prompt:** "Start M4: correlation and timeline per MILESTONES.md. Show me the timeline for scenario 1 with skew injected."

---

## M5 — Detectors + `investigator correlate` CLI ⬜
**Scope**
- `investigator/detectors/`: one module per rule, keyed on source/role and message patterns, never on service names:
  - `upstream_timeout`, `retry_amplification`, `kafka_produce_failure`, `consumer_lag_growth`, `consumer_processing_error`, `db_config_anomaly`, `db_error_burst`, `first_error_per_service`.
- `investigator/analysis.py`:
  - Build candidate `Hypothesis` chains (cause finding precedes and links to effect findings).
  - Compute `ConfidenceFactor`s and the `confidence_cap`, then assemble the `AnalysisBundle`.
- `investigator/cli.py`: `investigator correlate --inputs <dir> [--skew-tolerance-ms N] --json`. Register the console script.

**Tests:** each detector on a minimal positive and negative fixture; scenario 1 bundle snapshot; the cap rules (e.g. a missing source means at most MEDIUM, no ID linkage means at most LOW).

> **Kickoff prompt:** "Start M5: detectors and the correlate CLI per MILESTONES.md. List the confidence-cap rules for my approval before coding them."

---

## M6 — Scenarios 2–4 + robustness harness ⬜
**Scope**
- Generators for db-config, consumer-lag, and ambiguous (expected: INSUFFICIENT).
- `tests/robustness/`: for every scenario × perturbation (rename all services, shift times by ±days, shuffle, drop N% non-critical records, add duplicates, add skew below tolerance, malformed lines), assert the same detector findings (by kind) and the same cap.

**Done when:** the full matrix is green, and the user reviews scenarios 2–4 sample output.

> **Kickoff prompt:** "Start M6: scenarios 2–4 and the robustness matrix per MILESTONES.md."

---

## M7 — Report model, validator, Markdown renderer ⬜
**Scope**
- `investigator/report/model.py`: `IncidentReport` with all required sections (summary, correlation ID, timeline, root cause or `unknown`, evidence, downstream symptoms, alternative hypotheses, confidence with named factors, next steps).
- `report/validate.py`: rejects unknown event IDs, confidence above the cap, a root cause without evidence, missing sections, and HIGH/MEDIUM with `unknown` root cause. Errors are machine-readable so the agent can retry.
- `report/render_md.py`: JSON → Markdown (D4).

**Tests:** one rejection test per rule; a valid report round-trips JSON → Markdown.

> **Kickoff prompt:** "Start M7: report model, validator and Markdown renderer per MILESTONES.md."

---

## M8 — SKILL.md + JSON allowlist + command runner ⬜
**Scope**
- `.claude/skills/incident-logs/SKILL.md` per the outline in PROPOSAL §5, with the fenced JSON allowlist (D1).
- `investigator/allowlist.py`: extracts the JSON block and checks an argv against it (exact subcommand, allowed flags, no shell metacharacters).
- `adapters/MockCliSource`: runs allowlisted commands via `subprocess` with an argv list (no shell).
- First SKILL_CHANGELOG entry.

**Tests:** allowed commands pass; disallowed subcommands, flags, pipes, `;` and `$(...)` are rejected; SKILL.md parses; every command in SKILL.md's examples is allowlisted.

> **Kickoff prompt:** "Start M8: SKILL.md, the allowlist and the CLI runner per MILESTONES.md. Show me the SKILL.md draft before wiring it in."

---

## M9 — Provider interface, fake LLM, tool loop, transcripts ⬜
**Scope**
- `agent/provider.py`: `LLMProvider` protocol and a `ScriptedFakeLLM` that plays back scripted turns.
- `agent/tools.py`: `run_command` (allowlisted), `correlate`, `submit_report`.
- `agent/loop.py`: tool-use loop with a turn budget. On validator rejection it feeds the errors back, up to **3 retries (D12)**, then fails closed to INSUFFICIENT.
- `narration.py`: bundle → compact deterministic context for the prompt.
- Transcript writer → `runs/<ts>-<scenario>.jsonl` (append-only, never deletes).

**Tests:**
- End-to-end with the fake LLM for all 4 scenarios.
- A fake LLM that cites a bogus event ID is rejected and then retried.
- A fake LLM that never complies ends INSUFFICIENT after 3 retries.
- Transcript file written and complete.

> **Kickoff prompt:** "Start M9: provider interface, fake LLM, tool loop and transcripts per MILESTONES.md."

---

## M10 — Real provider + offline replay ⬜ (needs `ANTHROPIC_API_KEY`)
**Scope**
- `AnthropicProvider` over stdlib `urllib`. Model `claude-sonnet-5-5` (D10); key from env only, with a clear error if it's missing.
- `investigator replay runs/<file>.jsonl` (D3).

**Tests:** provider against a mocked transport (no network); replay reproduces the report.

**Manual step:** the user sets the key, then one real run per scenario is saved to `runs/`.

> **Kickoff prompt:** "Start M10: Anthropic provider and replay per MILESTONES.md. I've exported ANTHROPIC_API_KEY."

---

## M11 — Claude Code subagent + allowlist hook ⬜
**Scope**
- `.claude/agents/incident-investigator.md` with `skills: [incident-logs]` in frontmatter (verify syntax against current docs first, R2).
- `.claude/hooks/allowlist_guard.py` PreToolUse hook (D7).
- Transcript capture into `runs/` (R4).
- SKILL_CHANGELOG entries for each change triggered by a run.

**Tests:** hook unit tests (allowed/denied JSON in → decision out); manual subagent run per scenario saved.

> **Kickoff prompt:** "Start M11: subagent, allowlist hook and transcript capture per MILESTONES.md. Verify the frontmatter syntax first and tell me what you found."

---

## M12 — README + demo script ⬜
**Scope:** a README (what it is, the synthetic-data disclaimer, architecture diagram, how to run each path, how to read a report), a `demo.sh` that runs the offline replay of all 4 scenarios, and a clean-checkout walkthrough.

> **Kickoff prompt:** "Start M12: README and demo script per MILESTONES.md."
