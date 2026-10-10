# CLAUDE.md: Incident Log Investigator (demo)

A demo for a job interview. It is a simplified rebuild of an AI log-investigation tool the user built at their current employer. That original belongs to the employer, so this project uses **only synthetic data and generic names**: no real company, service, schema, customer, or person names anywhere (code, fixtures, docs, commit messages, transcripts).

Design proposal: `docs/design/PROPOSAL.md`. The milestone plan and the current milestone are tracked there.

## Process documentation (MANDATORY, every session)

The user needs a real, unpolished record of how they work with AI. These rules are not optional and apply to every message.

1. **`docs/process/PROMPT_LOG.md`**: for EVERY user message, append it **VERBATIM** (exact text, typos included) **BEFORE doing any work**, with a timestamp (UTC + local) and the current milestone. Never edit, summarize, reorder, or clean up earlier entries. After finishing the task, append a short **Outcome** under that entry: what was done, files changed, and the commands/tests run with their **actual** results.
2. **`docs/process/AI_NOTES.md`**: log every time the user corrects the AI, rejects a suggestion, or redirects scope: what was proposed, what the user said (quoted), and what changed. Also log mistakes the AI catches itself (a failing test, a wrong assumption). Entries are factual. Never invent, exaggerate, or flatter.
3. **`docs/process/SKILL_CHANGELOG.md`**: every change to `.claude/skills/incident-logs/SKILL.md` or `.claude/agents/incident-investigator.md` gets an entry with the reason and the run transcript (path under `runs/`) that triggered it.
4. **`runs/<timestamp>-<scenario>.jsonl`**: save every agent run's full transcript. Never delete old runs.
5. **Small git commits** whose messages explain *why*, not just *what*.

## Engineering rules

- **Python 3.9+** (the machine has 3.9.6; the user chose not to install 3.11, decision D1 on 2026-10-10). Type hints, dataclasses, **stdlib + pytest only**. **Ask before adding ANY other dependency.**
  - 3.9 compatibility: put `from __future__ import annotations` in every module; no `match`, no `X | Y` outside annotations (use `Optional`/`Union` in `isinstance` and type aliases), no `dataclass(slots=/kw_only=)`, no `tomllib`/`StrEnum`/`ExceptionGroup`. `datetime.fromisoformat` does not accept a `Z` suffix, so normalize it first.
- The SKILL.md command allowlist is a **fenced JSON block** (not TOML), so it can be read with stdlib `json` on 3.9.
- Keep module boundaries clear: adapters, parsing/normalization, correlation, timeline, detectors, analysis, narration, report, CLI.
- Handle malformed records, missing IDs, timestamp skew, duplicates, and out-of-order logs.
- **Never hardcode a root cause for a scenario.** The analysis code must not know scenario names or the injected fault. Robustness tests rename services, shift times, shuffle order, and drop records.
- The LLM never parses raw logs or decides chronology. Deterministic code does that, and the LLM reasons over the structured output.
- Every conclusion cites event IDs. Citations to non-existent event IDs are rejected by the validator.
- **No secrets in code or config.** The API key comes from an environment variable only.
- **Never claim tests passed unless they were actually run.** Paste the real output.
- Work in small milestones. Do only the agreed scope, then **stop and wait for the user**.
