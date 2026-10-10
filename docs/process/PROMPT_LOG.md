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

---

## Entry 002 — 2026-10-10T17:21:23Z (10:21 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim)

````text
For d1 is oython 3.11+ that important for the project to run, if not dont. need it
````

### Outcome

- **Did:** Answered the question; no files changed other than this log. D1 is still open until the user picks an option.
- **Commands run:** `/usr/bin/python3 -c "import tomllib"` → `ModuleNotFoundError: No module named 'tomllib'`. `/usr/bin/python3 -m pytest --version` → `No module named pytest`.
- **Finding:** Under the current spec, the only hard dependency on 3.11 is `tomllib`, used to read the TOML allowlist in SKILL.md. Separately, pytest has to be installed whichever Python is used.

---

## Entry 003 — 2026-10-10T17:22:21Z (10:22 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim)

````text
follow option 2 dont need to complciate it
````

### Outcome

- **Did:** Applied D1 option 2. The target is now Python 3.9+, and the SKILL.md allowlist is a fenced JSON block instead of TOML. Added 3.9 compatibility rules to CLAUDE.md. Updated PROPOSAL.md (data flow, module notes, SKILL outline sample, R1, R3, M8, new section 8 Decisions). Logged the redirect in AI_NOTES. Finished at 2026-10-10T17:22:49Z.
- **Files:** `CLAUDE.md`, `docs/design/PROPOSAL.md`, `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** `sed` replacements of TOML→JSON references. A `grep -i "toml|3.11|tomllib"` afterwards showed only intentional mentions remaining (the 3.9 rule note, the "JSON rather than TOML" rationale, `pyproject.toml` for packaging).
- **Tests:** none (no code yet).
- **Still open:** D2–D12, then approval to start M1. pytest is not installed for Python 3.9 yet.

---

## Entry 004 — 2026-10-10T17:25:50Z (10:25 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim)

````text
D2 keep thje clock skew tolereance as 1 min because we have seen kafak events reflected after a 1 min, we will keep 1 min than we will tune it
````

### Outcome

- **Did:** Recorded D2 = 60 000 ms (1 min) default skew tolerance, configurable, to be tuned. Added risk R6b (wide tolerance vs ordering precision; delivery delay vs clock skew) with mitigations. Logged the rejected 2000 ms suggestion in AI_NOTES. Finished at 2026-10-10T17:26:05Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** a Python string replace on PROPOSAL.md, then `grep` confirmed that the D2 row (line 157) and the R6b row (line 126) are present.
- **Tests:** none (no code yet).
- **Still open:** D3–D12, approval for M1.

---

## Entry 005 — 2026-10-10T17:26:23Z (10:26 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim)

````text
Show me what decisisons are pending
````

### Outcome

- **Did:** Listed the pending decisions D3–D12 in chat, with recommendations (copied from the M0 proposal message). No project files changed.
- **Commands run:** none besides appending this entry.
- **Tests:** none.

---

## Entry 006 — 2026-10-10T17:29:15Z (10:29 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim; first block was pasted by the user, tabs preserved)

````text
D3	Offline demo mode: replay recorded transcripts, or a rule-based fallback?	Replay recorded transcripts from runs/, so the demo shows real AI behavior. The scripted fake AI stays test-only.
D4	Report output format	JSON is the validated source of truth, and Markdown is generated from it.
D5	Mock log formats	Mixed: JSON lines for app services; text in each tool's native style for Kafka and the DB, so the parsers get real work.
D6	Generic names	order-api, fulfillment-worker, notification-worker, edge-gateway, upstream partner-pricing, topic orders.events, consumer group fulfillment-consumers, DB appdb. Veto any that resemble your employer's.
D7	Allowlist enforcement for the Claude Code subagent	A hook that checks each shell command against the same JSON allowlist before it runs.

I am fine with this
````

### Outcome

- **Did:** Recorded D3–D7 as resolved, all as recommended, in the PROPOSAL.md Decisions table. D8–D12 were not included in the pasted rows, so they remain open. Finished at 2026-10-10T17:29:20Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** a Python script appended this entry (keeping the pasted tabs) and updated the table. `grep` confirmed rows D1–D7 resolved and D8–D12 open.
- **Tests:** none (no code yet).

---

## Entry 007 — 2026-10-10T17:30:24Z (10:30 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim; tabs preserved)

````text
D8	Scenario data	Generated by seeded code with adjustable settings (rename, time shift, drop, shuffle), with snapshot outputs checked in.
D9	Packaging	pyproject.toml with setuptools only as the build tool, so mocklogs and investigator work as plain commands. Otherwise everything runs as python3 -m ....
D11	When to push to GitHub	After each approved milestone.
D12	Max retries when the validator rejects a report	2, then the report falls back to "insufficient evidence".

for d12 keep it 3 we will tune it later based on data
````

### Outcome

- **Did:** Recorded D8, D9 and D11 as recommended, and D12 = 3 retries (user override of 2). D10 was not in the message, so it is still open. Found that D9's editable install would fail with the system pip/setuptools, added it as risk R11, and proposed a project-local `.venv`. Logged the D12 override and two self-caught issues in AI_NOTES. Finished at 2026-10-10T17:30:49Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:**
  - `python3 -m pip --version` → `pip 21.2.4 ... (python 3.9)`
  - `python3 -c "import setuptools; print(setuptools.__version__)"` → `setuptools 58.0.4`
  - A Python script edited the decisions table, inserted R11 (initially before R7) and then moved it after R10. `grep` confirmed R1…R11 are in order and D1–D12 have the expected status.
- **Tests:** none (no code yet).
- **Still open:** D10, the OK for a project `.venv` (R11), and approval to start M1.

---

## Entry 008 — 2026-10-10T17:31:09Z (10:31 PDT) — Milestone: M0 (decisions pending)

### Prompt (verbatim; tabs preserved)

````text
D10	Default model and API key variable	claude-sonnet-5-5, with the key read from ANTHROPIC_API_KEY.
D11	When to push to  I dont have a key now, will provide later.
````

### Outcome

- **Did:** Recorded D10 as resolved (`claude-sonnet-5-5`, `ANTHROPIC_API_KEY`), noting that no key is available yet and only the M10 real-API runs depend on one. The "D11 When to push to" fragment looked like a partial paste; D11 was already resolved in entry 007, so nothing changed for it. All D1–D12 are now resolved. Finished at 2026-10-10T17:31:09Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** a Python script appended this entry and updated the D10 row.
- **Tests:** none (no code yet).
- **Still open:** the OK for a project `.venv` (R11) and approval to start M1.

---

## Entry 009 — 2026-10-10T17:32:53Z (10:32 PDT) — Milestone: M0 (environment setup)

### Prompt (verbatim)

````text
1. OK to create the project `.venv`? It upgrades pip and setuptools inside `.venv/` only and installs pytest there. Yes i need a .venv to keep the enivronemnt contanireresd
````

### Outcome

- **Did:** Created the project venv and installed upgraded pip/setuptools plus pytest inside it only (the system Python is untouched). Marked R11 resolved in PROPOSAL.md and added an Environment rule to CLAUDE.md (always use `.venv/bin/...`). M1 has not been approved yet, so no M1 work was started. Finished at 2026-10-10T17:33:09Z.
- **Files:** `CLAUDE.md`, `docs/design/PROPOSAL.md`, `docs/process/PROMPT_LOG.md` (`.venv/` is gitignored)
- **Commands run:**
  - `python3 -m venv .venv && .venv/bin/pip install -q -U pip setuptools pytest` → exit 0
  - `.venv/bin/python --version` → `Python 3.9.6`
  - `.venv/bin/pip --version` → `pip 26.0.1 ... (python 3.9)`
  - setuptools version → `setuptools 82.0.1`
  - `.venv/bin/pytest --version` → `pytest 8.4.2`
  - `git status --short` → only `docs/process/PROMPT_LOG.md` modified (`.venv/` correctly ignored)
- **Tests:** none (no code yet).
- **Still open:** approval to start M1.
