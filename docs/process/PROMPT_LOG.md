# Prompt Log

Every message the user sends is appended here VERBATIM (exact text, typos included) before any work starts, with a timestamp and the current milestone. Earlier entries are never edited, summarized, reordered, or cleaned up. After the task, a short outcome is appended under the entry.

---

## Entry 001 — 2026-10-10T17:17:17Z (10:17 PDT) — Milestone: M0 (process setup + design proposal)

### Prompt (verbatim)

````text
I'm building a demo project for a job interview. It's a simplified rebuild of an AI log-investigation tool I built at my current job. That original belongs to my employer, so this rebuild must use only synthetic data and generic names: no real company, service, schema, customer, or person names anywhere.

## What we're building
An AI agent that investigates distributed-system incidents:
- Mock CLIs (`mocklogs`) serve synthetic logs from four sources: app services, an upstream dependency, Kafka (producer/broker/consumer, consumer lag), and a database (logs + config). Every output is clearly labeled MOCK. Shape the commands like real tools (kubectl logs, kafka-consumer-groups, psql-style config dumps) so they can be swapped for real integrations later.
- A skills file (.claude/skills/incident-logs/SKILL.md) tells the agent which CLI to use for which source, the exact command syntax, the output format, and the order to investigate in. It includes a machine-readable TOML block that serves as the command allowlist.
- A deterministic `investigator correlate` command parses, normalizes, dedupes, and correlates logs by correlation/trace/message ID, then builds a timeline with clock-skew tolerance and runs rule-based detectors. The LLM never parses raw logs or decides chronology itself.
- The LLM reasons over that structured output and concludes with a root cause OR an explicit "insufficient evidence". It must cite event IDs. A validator rejects citations to event IDs that don't exist.
- Two ways to run the agent, sharing the same tools:
  (1) A Claude Code subagent at .claude/agents/incident-investigator.md, with the skill listed explicitly in its frontmatter.
  (2) My own Python tool-use loop behind an LLM-provider interface. The API key comes from an env var only. A scripted fake LLM is used for tests.
- The report includes: summary, correlation ID, timeline, root cause or "unknown", evidence referencing actual log records, downstream symptoms, alternative hypotheses, confidence rationale (categorical HIGH/MEDIUM/LOW/INSUFFICIENT with named factors, not a float), and next diagnostic steps.
- Four scenarios: upstream timeout → retries → Kafka failures; DB config error → DB failures; Kafka consumer lag/processing failure → downstream symptoms; and an ambiguous incident with insufficient evidence.

## Engineering rules
- Python 3.11+, type hints, dataclasses, stdlib + pytest only. Ask before adding ANY other dependency.
- Keep module boundaries clear: adapters, parsing/normalization, correlation, timeline, detectors, analysis, narration, report, CLI.
- Handle malformed records, missing IDs, timestamp skew, duplicates, and out-of-order logs.
- Never hardcode a root cause for a scenario. Add robustness tests that rename services, shift times, shuffle order, and drop records.
- No secrets in code or config.
- Never claim tests passed unless you ran them. Paste the real output.
- Work in small milestones. Do only the agreed scope, then stop and wait for me.

## Process documentation (IMPORTANT, set this up first)
I need a real, unpolished record of how I work with AI for the interview. Put these rules in CLAUDE.md so they persist across sessions:

1. docs/process/PROMPT_LOG.md: for every message I send you, append it VERBATIM (exact text, typos included) BEFORE doing any work, with a timestamp and the current milestone. Never edit, summarize, reorder, or clean up earlier entries. Then, after finishing the task, append a short outcome under it: what you did, files changed, and the commands/tests you ran with their actual results.
2. docs/process/AI_NOTES.md: log every time I correct you, reject a suggestion, or redirect scope. Record what you proposed, what I said (quoted), and what changed. Also log mistakes you catch yourself (a failing test, a wrong assumption). Keep entries factual. Don't invent, exaggerate, or flatter.
3. docs/process/SKILL_CHANGELOG.md: every change to SKILL.md or the subagent file gets an entry with the reason and the run transcript that triggered it.
4. Save every agent run's full transcript to runs/<timestamp>-<scenario>.jsonl, and keep them (don't delete old runs).
5. Make small git commits with messages that explain why, not just what.

## First task (do ONLY this)
1. Create CLAUDE.md with the rules above and the docs/process/ files, then log this message as the first PROMPT_LOG entry.
2. Propose: the architecture and data flow, module structure and data models, the SKILL.md outline, the main technical risks and assumptions, and a milestone plan where each milestone is small and testable.
3. List the decisions you need from me (e.g., default skew tolerance, whether offline demo mode replays recorded transcripts or uses a rule-based fallback, Markdown vs JSON report output).

Do not write implementation code yet. Wait for my approval.
````

### Outcome

- **Did:** Created CLAUDE.md with the process and engineering rules, the three docs/process files, `runs/README.md`, `.gitignore`, and the design proposal at `docs/design/PROPOSAL.md`. Logged this message verbatim before starting work. No implementation code was written.
- **Files:** `CLAUDE.md`, `.gitignore`, `docs/process/PROMPT_LOG.md`, `docs/process/AI_NOTES.md`, `docs/process/SKILL_CHANGELOG.md`, `runs/README.md`, `docs/design/PROPOSAL.md`
- **Commands run:**
  - Python version check: only `/usr/bin/python3` → `Python 3.9.6`. `python3.11`, `python3.12` and `python3.13` were not found. Logged in AI_NOTES; this is decision D1.
  - `git commit` ×2 → `b8a466a Set up process logging before any code exists`, `b8cf2c2 Propose architecture and milestones for review before coding`
- **Tests:** none. No code exists yet.
- **Status:** Waiting for the user to approve the proposal and answer decisions D1–D12.
