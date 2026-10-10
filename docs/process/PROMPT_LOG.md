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

---

## Entry 010 — 2026-10-10T17:33:33Z (10:33 PDT) — Milestone: M0 (awaiting approval)

### Prompt (verbatim)

````text
What is m0?
````

### Outcome

- **Did:** Explained in chat what M0 is and what it delivered. No project files changed.
- **Commands run:** `git log --oneline | wc -l` to count the commits so far.
- **Tests:** none.

---

## Entry 011 — 2026-10-10T17:34:27Z (10:34 PDT) — Milestone: M0 approved → M1 (skeleton, models, pytest wiring)

### Prompt (verbatim)

````text
yes push it and start m1
````

### Outcome

- **Did:** Pushed the M0 commits to GitHub (`main -> main`, upstream set). Implemented M1:
  - `pyproject.toml`: setuptools backend, src layout, `requires-python >=3.9`, no runtime deps, optional `test` extra, pytest config. Console scripts are deferred to the M2/M5 milestones that build those CLIs, so no entry point points at missing code.
  - Two top-level packages `investigator` and `mocklogs` (`__init__` only). Subpackages are created in the milestones that need them.
  - `investigator/models.py`: Source, Level, Confidence (categorical, ordered, `at_most`), FactorValue, LinkKind, ParseIssueKind, RawRecord, ParseIssue, Ids, Event (UTC-only, non-empty ID), CorrelationGroup, SkewEstimate, TimelineEntry, Finding (must cite ≥1 event), Hypothesis, ConfidenceFactor, AnalysisBundle (default skew tolerance 60 000 ms per D2), and `to_jsonable`.
  - Tests: `tests/unit/test_models.py` (9) and `tests/unit/test_import_boundary.py` (2: no `mocklogs` import, no D6 scenario names in `investigator`).
- **Files:** `pyproject.toml`, `src/investigator/__init__.py`, `src/investigator/models.py`, `src/mocklogs/__init__.py`, `tests/unit/test_models.py`, `tests/unit/test_import_boundary.py`, `docs/design/PROPOSAL.md`, `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`
- **Commands run (actual results):**
  - `git push -u origin main` → `* [new branch] main -> main`
  - `.venv/bin/pip install -q -e .` → no output. The exit code was not captured (zsh/`PIPESTATUS` slip, see AI_NOTES). `pip show` → `Editable project location: /Users/goodvibesonly/log-analyzer-demo`
  - `.venv/bin/pytest` → `collected 11 items` … `11 passed in 0.02s` (Python 3.9.6, pytest-8.4.2)
  - Canary check: temporarily added `src/investigator/_canary_violation.py` (`import mocklogs` + `"order-api"`) → `2 failed` with `investigator imports mocklogs at: ['investigator/_canary_violation.py:1']` and `scenario vocabulary found in investigator: ['investigator/_canary_violation.py: order-api']`. Removed the file, then `.venv/bin/pytest` → `11 passed in 0.01s`.
- **Not pushed:** M1 awaits review (D11: push after approval).

---

## Entry 012 — 2026-10-10T17:38:32Z (10:38 PDT) — Milestone: M1 (awaiting review)

### Prompt (verbatim)

````text
Give all the steps planned, i will review the prompts and modify them and the design as well
````

### Outcome

- **Did:** Wrote `docs/design/MILESTONES.md` for the user to review and edit. It expands every milestone M0–M12 with scope, tests, done-when, and a suggested kickoff prompt, and it marks status (M0 ✅, M1 🟡, rest ⬜). Linked it from PROPOSAL.md §7. No code changed. M1 is still awaiting review and is not pushed. Finished at 2026-10-10T17:39:17Z.
- **Files:** `docs/design/MILESTONES.md` (new), `docs/design/PROPOSAL.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** `sed` to add the link, then `grep` to confirm it.
- **Tests:** none run (no code changed since M1's `11 passed`).

---

## Entry 013 — 2026-10-10T17:41:02Z (10:41 PDT) — Milestone: M0 design under user review (M1 on hold)

### Prompt (verbatim)

````text
Wait i am reviewing m0 the design
````

### Outcome

- **Did:** Acknowledged and paused. No work done, no files changed besides this log. M1 stays unpushed. No M2 work.
- **Commands run:** none besides appending this entry.
- **Tests:** none.

---

## Entry 014 — 2026-10-10T17:46:42Z (10:46 PDT) — Milestone: M0 design revision (M1 on hold)

### Prompt (verbatim)

````text
Changed somethings to the design plan, Are you defiing what an error is w.r.t each components, the components here are kafka logs, application logs, application config, db logs. The order should be that first you will give be given application log with the errros message than contains the application name, you have to go the config files for that application for which you have access and then go the kafka outputs/inputs to the applications, fetch the logs from kafka upstream downstram, related application logs using a common identifer and thread numbers and also if any downstream db is present that logs as well. This si the flow, modify the design accordingly
````

### Outcome

- **Did:**
  - Checked for the user's design edits: none were on disk or on GitHub at first (`git diff`, `git fetch` + compare). Treated the message as the change request.
  - Answered the question: Rev 1 did not define errors per component.
  - Wrote the Rev 2 design as `docs/design/PROPOSAL_REV2_DRAFT.md`: seed-driven traversal, per-component error definitions, thread segments, planner, revised models/scenarios/SKILL outline/risks/milestones, open decisions D13–D20 + Q1.
  - Mid-task the user edited `PROPOSAL.md` (10:48, removed "data-quality issues" from §1 item 3). My write to `PROPOSAL.md` was rejected as stale, so I did not overwrite it. The user's edit is uncommitted and untouched.
  - M1 code not changed; no M2 work. Finished at 2026-10-10T17:50:30Z.
- **Files:** `docs/design/PROPOSAL_REV2_DRAFT.md` (new), `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`. Not committed by me: the user's own edit to `docs/design/PROPOSAL.md`.
- **Commands run:** `git status`/`git diff` (no design edits at first); `git fetch` + `git log main..origin/main` (no remote commits); `git diff -- docs/design/` after the write rejection (showed the user's one-line edit).
- **Tests:** none (design only).

---

## Entry 015 — 2026-10-10T17:53:33Z (10:53 PDT) — Milestone: M0 design Rev 2 decisions (M1 on hold)

### Prompt (verbatim)

````text
Q1. Data quality issues dont need it.  D13 partner pricing upstream is kafaka events,  D14 yes. D15 only one way upstreama nd downstram. D16 yes, D17 for application logs keep it 1 min. D18 is fine. D19 yes app log is given as agents first message. Dont need to check for config change histroy
````

### Outcome

- **Did:**
  - Committed the user's own 10:48 edit to `PROPOSAL.md` separately (`d15deee`) so it stays in history.
  - Merged the Rev 2 draft plus the user's decisions into `PROPOSAL.md`:
    - Q1: data-quality issues dropped.
    - D13: `partner-pricing` is a Kafka upstream app; scenario 1 reworked with a proposed topic `pricing.events`.
    - D14: DB server config dropped.
    - D15: exactly 1 hop each way.
    - D16: access list.
    - D17: 1-min thread window.
    - D18: deterministic planner.
    - D19: seed = agent's first message.
    - D20: no config history; scenario 2 now uses `config.inconsistent`.
    - Added risks R17 (getting the seed into the planner) and R18 (no change history).
  - Rewrote `MILESTONES.md` to Rev 2 (M0–M14 with kickoff prompts).
  - Deleted the now-merged draft file. Logged the decision diffs in AI_NOTES.
  - No code changed; M1 stays on hold. Finished at 2026-10-10T17:55:27Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/design/MILESTONES.md`, `docs/design/PROPOSAL_REV2_DRAFT.md` (deleted), `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** `git status`/`git diff --stat` (only the user's one-line edit present); `git commit` of the user's edit → `d15deee`; `git rm` of the draft.
- **Tests:** none (design only).

---

## Entry 016 — 2026-10-10T17:58:07Z (10:58 PDT) — Milestone: M0 design Rev 2 confirmations (M1 on hold)

### Prompt (verbatim)

````text
1. Topic name `pricing.events`: scenario 1 needs a topic for pricing events, and this is the name I made up. OK? Yes, make up the topic names.
2. Thread link rule: you said keep it to 1 minute. I also kept "stop early if the thread starts logging a different correlation ID", so two requests sharing a thread don't get merged. Keep that, or use the 1-minute window only?  Yes that makes sense
3. Related apps' configs: I fetch config only for the seed app, not for the upstream and downstream apps, which matches your flow. OK? Yes.
4. Getting the seed to the planner: with the seed arriving in chat, the code has to save it to a file without the AI retyping or parsing it. My own Python loop can do that directly. For the Claude Code subagent I'll work out the mechanism in M10/M13, and it's logged as risk R17. Yes that works
````

### Outcome

- **Did:** Recorded all four confirmations in PROPOSAL.md:
  - `pricing.events` confirmed, and the AI may invent further generic topic names (D6, §4);
  - thread segment = 1-min window + early stop at a different correlation ID (D17);
  - configs fetched only for the seed app (§1 step 4);
  - the R17 approach confirmed.
  No AI_NOTES entry: these confirmed the AI's proposals rather than correcting them. No code changed. Finished at 2026-10-10T17:58:07Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** a Python script with assert-guarded string replacements (all 6 matched).
- **Tests:** none (design only).
- **Still open:** explicit go-ahead to update M1 models to Rev 2.

---

## Entry 017 — 2026-10-10T18:03:34Z (11:03 PDT) — Milestone: M0 design Rev 2 amendment (M1 on hold)

### Prompt (verbatim; the user sent the first version, interrupted it, then sent the second)

````text
For traversal to fetch the kafka logs, take user as authenticator. user sso as there is no agent login vailaable.
````

_[Request interrupted by user]_

````text
For traversal to fetch the kafka logs, take user sso for authentication as there is no agent login credentials vaialbel.
````

### Outcome

- **Did:**
  - Committed the user's own uncommitted annotation in PROPOSAL.md §1 step 2 ("(Yes this is important)") separately as `b5016bc`.
  - Added Kafka SSO auth to the design:
    - D21, plus new §1.2 (user-only login, session check on `kafka-*` commands, stop-and-ask on expiry, `auth_required` coverage gap, no session material in artifacts);
    - `mocklogs/sso.py` in the module tree; risk R19; the SKILL outline auth rules;
    - M2 (mock SSO + tests) and M10 (`sso login` excluded from the allowlist) scope in MILESTONES.md.
  - No code changed; M1 still on hold. Finished at 2026-10-10T18:04:14Z.
- **Files:** `docs/design/PROPOSAL.md`, `docs/design/MILESTONES.md`, `docs/process/AI_NOTES.md`, `docs/process/PROMPT_LOG.md`
- **Commands run:** `git diff -- docs/design/` (found the user's one-line edit); a Python script with count-asserted replacements (all matched); `grep` confirmed D21/R19/`auth_required` in both files.
- **Tests:** none (design only).
- **Open:** does SSO apply only to Kafka, or to app logs / config / DB logs too? Go-ahead for the M1 model update.
