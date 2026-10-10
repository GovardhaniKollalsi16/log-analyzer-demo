# Design Proposal (M0, awaiting approval)

Status: **PROPOSED, not approved.** No implementation code exists yet.

## 1. Architecture & data flow

```
                ┌──────────────── agent runtime (either) ────────────────┐
                │ (1) Claude Code subagent   (2) Python tool-use loop    │
                │     + SKILL.md                 + LLMProvider (real/fake)│
                └───────┬──────────────────────────────┬─────────────────┘
                        │ allowlisted commands only    │ submit_report(json)
                        ▼                              ▼
  mocklogs CLI (MOCK-labeled raw text)      report validator ──► report.json + report.md
     kubectl logs │ upstream │ kafka-* │ psql         ▲ (citations must exist,
                        │                           │  confidence ≤ cap)
                        ▼                           │
  investigator correlate (deterministic, no LLM) ───┘
     adapters → parse/normalize → dedupe → correlate (ID graph)
              → timeline (skew-tolerant) → detectors → analysis bundle (JSON)
```

1. The agent reads SKILL.md and follows its investigation order: app services → upstream → Kafka → DB. It can **only** run commands in the JSON allowlist.
2. `mocklogs` prints synthetic raw logs shaped like real tools. Every output starts with a `MOCK` banner, and each record carries a source tag.
3. `investigator correlate` turns raw outputs into one **analysis bundle** (JSON). The bundle holds normalized events with stable `event_id`s, correlation groups, an ordered timeline with uncertainty flags, detector findings, data-quality issues, source coverage, and a **confidence cap**.
4. The LLM reasons only over the bundle, then calls `submit_report`. The validator rejects unknown event IDs, a confidence above the deterministic cap, a root cause without evidence, and missing required sections. On rejection the agent gets the errors back and can retry (bounded).
5. Every turn and tool call is appended to `runs/<ts>-<scenario>.jsonl`.

**Key principle:** chronology, parsing, and correlation are deterministic and testable. The LLM's job is reduced to *choosing among and explaining* evidence-backed hypotheses, or declaring INSUFFICIENT.

## 2. Module structure

```
pyproject.toml                 # (pending decision D9) console scripts: mocklogs, investigator
src/
  mocklogs/                    # MOCK data side. Analysis code must NEVER import this.
    cli.py                     # kubectl / upstream / kafka-* / psql-style subcommands
    scenarios/                 # parameterized generators (seed, service names, t0, skew, drop%, dup%, shuffle)
    render.py                  # emits text in each tool's native-looking format + MOCK banner
  investigator/
    models.py                  # dataclasses (below)
    adapters/                  # LogSource protocol; MockCliSource runs allowlisted argv via subprocess (no shell)
    parsing/                   # one parser per format → RawRecord → Event; ParseIssue for malformed
    normalize.py               # UTC timestamps, level mapping, ID extraction, stable event_id
    dedupe.py
    correlation.py             # union-find over correlation_id / trace_id / message_id (+ request_id)
    timeline.py                # per-source skew estimation, tolerance-based ordering, uncertainty flags
    detectors/                 # one module per rule; generic over service *roles*, never names
    analysis.py                # bundle assembly: coverage, candidate chains, confidence cap
    allowlist.py               # parses the fenced JSON allowlist block out of SKILL.md (stdlib json)
    agent/
      provider.py              # LLMProvider protocol, AnthropicProvider (urllib), ScriptedFakeLLM
      loop.py                  # tool-use loop, turn budget, transcript writer
      tools.py                 # run_command (allowlisted), correlate, submit_report
    narration.py               # bundle → compact prompt context (deterministic summarization)
    report/
      model.py  validate.py  render_md.py
    cli.py                     # investigator correlate | run | validate | replay
.claude/
  skills/incident-logs/SKILL.md
  agents/incident-investigator.md
  hooks/allowlist_guard.py     # (pending D7) PreToolUse hook enforcing the JSON allowlist for the subagent
tests/  unit/  integration/  robustness/
runs/   docs/process/   docs/design/
```

## 3. Data models (dataclasses, sketch)

- `RawRecord(source, command, line_no, text)`: provenance of every raw line.
- `ParseIssue(source, line_no, kind: malformed|bad_timestamp|unknown_format, text)`
- `Event`: `event_id` (stable hash of source + raw text + occurrence index, e.g. `ev-7f3a9c`), `source` (app|upstream|kafka|db), `role`, `service`, `component`, `ts_raw`, `ts_utc`, `level`, `message`, `ids: Ids(correlation_id, trace_id, message_id, request_id)`, `attrs: dict`, `raw_refs: list[RawRecord]`, `duplicate_count`.
- `CorrelationGroup(group_id, ids: set, event_ids, link_kinds)`: links are `exact_id` or `weak_temporal` (only when no ID exists, always labeled).
- `TimelineEntry(event_id, adjusted_ts, skew_applied_ms, order_uncertain: bool, concurrent_with: list)`
- `SkewEstimate(source, offset_ms, basis: causal_pairs|none, samples)`
- `Finding(finding_id, detector, kind, event_ids, summary, attrs)`, e.g. `upstream_timeout`, `retry_amplification`, `kafka_produce_failure`, `consumer_lag_growth`, `consumer_processing_error`, `db_config_anomaly`, `db_error_burst`, `first_error_per_service`.
- `Hypothesis(hyp_id, cause_finding_ids, effect_finding_ids, precedence_ok, id_linked)`: candidates only, unranked by "truth".
- `ConfidenceFactors(id_linkage, source_coverage, temporal_precedence, competing_hypotheses, data_quality)`, each categorical. `confidence_cap: HIGH|MEDIUM|LOW|INSUFFICIENT` is computed from these.
- `AnalysisBundle(bundle_id, sources_queried, coverage_gaps, events, groups, timeline, findings, hypotheses, parse_issues, confidence_cap, factors)`
- `IncidentReport`: `summary`, `correlation_id | None`, `timeline[{event_id, ts, note}]`, `root_cause: {statement, event_ids} | "unknown"`, `evidence[{event_id, why}]`, `downstream_symptoms[{statement, event_ids}]`, `alternative_hypotheses[{statement, why_rejected_or_open, event_ids}]`, `confidence: {level, factors{name: value+reason}}`, `next_steps[]`.

## 4. Scenarios (data side only)

Generic names (proposal): `edge-gateway`, `order-api`, `fulfillment-worker`, `notification-worker`, upstream `partner-pricing` (fictional), topic `orders.events`, group `fulfillment-consumers`, DB `appdb`.

1. **upstream-timeout:** upstream latency → `order-api` timeouts → retries with backoff → producer request backlog → Kafka `TimeoutException`/delivery failures.
2. **db-config:** a config change (e.g. `max_connections` / pool size lowered, or `statement_timeout` too low) visible in the config dump → connection refusals / cancelled statements.
3. **consumer-lag:** a poison message causes repeated consumer processing failures → lag grows on one partition → downstream symptoms (stale status, missing notifications).
4. **ambiguous:** overlapping minor errors across sources, missing IDs, one source partially unavailable → expected conclusion INSUFFICIENT.

Each generator takes knobs: `seed`, `service_names` map, `t0`, `per_source_skew_ms`, `drop_rate`, `dup_rate`, `shuffle`, `malformed_rate`.

## 5. SKILL.md outline

1. Purpose & hard rules: never parse raw logs yourself; always run `investigator correlate`; cite event IDs only from the bundle; INSUFFICIENT is a valid and expected answer.
2. Source → CLI map (which tool for which source).
3. Exact command syntax per source, e.g.
   `mocklogs kubectl logs deploy/<svc> -n <ns> --since=<dur> --timestamps`,
   `mocklogs upstream access-log --dependency <name> --since=<dur>`,
   `mocklogs kafka-consumer-groups --describe --group <g>`,
   `mocklogs kafka logs --component producer|broker|consumer --since=<dur>`,
   `mocklogs psql -c "SHOW ALL"` / `mocklogs db logs --since=<dur>`,
   `investigator correlate --inputs <dir> --skew-tolerance-ms <n> --json`
4. Output format per source, with a short annotated sample of each including the MOCK banner.
5. Investigation order and stop conditions.
6. How to read the analysis bundle (findings, hypotheses, confidence cap).
7. Report contract: required sections, citation rules, confidence must be ≤ cap.
8. **Allowlist (machine-readable):**
   ```json
   {"allow": [
     {"tool": "mocklogs", "subcommand": ["kubectl", "logs"],
      "flags": ["-n", "--since", "--timestamps", "--tail"]}
   ]}
   ```
   One entry per command shape; anything else is rejected. (JSON rather than TOML: D1, Python 3.9 has no stdlib TOML reader.)

## 6. Technical risks & assumptions

| # | Risk / assumption | Mitigation |
|---|---|---|
| R1 | Python 3.9.6 is the target (D1 resolved: stay on 3.9). Python 3.9 no longer gets updates, and some newer syntax is unavailable. | Allowlist is JSON (stdlib `json`). 3.9 compatibility rules are in CLAUDE.md. pytest still has to be installed (M1). |
| R2 | Subagent frontmatter `skills:` field support and exact syntax depend on the Claude Code version. | Verify against current docs in that milestone and record the result in AI_NOTES. |
| R3 | A subagent's Bash tool can't natively enforce a JSON allowlist. | PreToolUse hook script that parses the same JSON block (D7). |
| R4 | Subagent transcripts live in `~/.claude/projects/...`, not `runs/`. | SubagentStop hook copies or converts them into `runs/`. Verify feasibility early. |
| R5 | "Never hardcode root cause" can leak through scenario-specific detectors or names. | Detectors keyed on roles/patterns. A test asserts `investigator` never imports `mocklogs` and contains no scenario or service names. Robustness tests rename everything. |
| R6 | Skew estimation from causal pairs can be wrong when there are few pairs. | Fall back to no correction plus wider uncertainty flags. Never reorder beyond tolerance. Mark `order_uncertain`. |
| R6b | With a 60 s tolerance (D2), cross-source events less than 1 min apart and with no shared ID are `order_uncertain`. Short incidents could then lose clear temporal precedence, which lowers the confidence cap. Also, a Kafka *delivery delay* (event consumed about 1 min after it was produced) is a different thing from *clock skew* (hosts disagreeing on the time). | Within one ID chain, causal order (produce → broker → consume) wins over timestamps, so ordering there stays exact regardless of tolerance. The bundle reports how many events were order-uncertain so tuning is evidence-based. Lag/delay is a measured detector signal, not absorbed into skew. |
| R7 | The LLM may still overclaim. | The validator enforces citations, confidence ≤ cap, and that the root cause cites ≥1 finding-backed event. Bounded retries, then fail closed to INSUFFICIENT. |
| R8 | The HTTP client is stdlib `urllib` (no SDK). | Small provider and a mocked-transport test. The real API is used only in manual runs. |
| R9 | Real-API runs are nondeterministic, so they aren't in CI. | Tests use ScriptedFakeLLM. Real runs are saved to `runs/`. |
| R10 | Synthetic data accidentally resembling the employer's system. | Generic vocabulary only. The user reviews scenario names and log shapes in M2. |

Assumptions: all timestamps are normalized to UTC; a single host runs everything; scenario data is generated (not hand-written) so knobs can perturb it; event IDs are stable across re-runs of the same input.

## 7. Milestone plan (each ends with tests run + stop for review)

| M | Scope | Done when |
|---|---|---|
| M0 | Process docs, CLAUDE.md, this proposal | User approves |
| M1 | Skeleton: pyproject, packages, `models.py`, pytest wiring, import-boundary test | `pytest` green (real output pasted) |
| M2 | `mocklogs` + scenario 1 generator, all four source formats, MOCK banners | Golden-output tests; user reviews log shapes |
| M3 | Parsers + normalization + malformed handling + dedupe | Unit tests incl. malformed/duplicate fixtures |
| M4 | Correlation (ID graph) + timeline with skew tolerance | Tests: shuffle, skew injection, missing IDs |
| M5 | Detectors + `investigator correlate` CLI → bundle JSON | Scenario 1 bundle snapshot test |
| M6 | Scenarios 2–4 + robustness harness (rename/shift/shuffle/drop) | Robustness suite green for all 4 |
| M7 | Report model, validator (citations, cap), Markdown renderer | Validator rejection tests |
| M8 | SKILL.md + JSON allowlist + `allowlist.py` | Allowlist parse/enforce tests; SKILL_CHANGELOG entry |
| M9 | Provider interface, ScriptedFakeLLM, tool loop, transcript writer | End-to-end fake-LLM tests for all 4 scenarios |
| M10 | Anthropic provider (env-var key), offline mode | Mock-transport test; one real run saved to `runs/` |
| M11 | Claude Code subagent + allowlist hook + transcript capture | Real subagent run per scenario saved; changelog entries |
| M12 | README + demo script | Clean-checkout walkthrough |

## 8. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Python version | **Resolved 2026-10-10:** stay on Python 3.9; the allowlist is JSON instead of TOML (user: "follow option 2 dont need to complciate it") |
| D2 | Default clock-skew tolerance | **Resolved 2026-10-10:** 60 000 ms (1 min), configurable via `--skew-tolerance-ms`; to be tuned later. Rationale (user): Kafka events have been seen reflected about 1 min late |
| D3–D12 | See chat on 2026-10-10 / PROMPT_LOG entry 001 outcome | Open |
