# AI Notes

A factual log of corrections, rejected suggestions, scope redirects, and mistakes the AI caught itself. Format per entry: date, milestone, what the AI proposed or did, what the user said (quoted) or what was detected, and what changed.

---

## 2026-10-10 — Pre-M0 (before these rules existed, same session)

- **Proposed/did:** Asked to "create a repo for demo project for log analyzer tool", the AI assumed a full project was wanted. It started scaffolding a Python log-analyzer CLI (`parser.py`, `analyzer.py`, then a `cli.py` write) in `~/log-analyzer-demo`.
- **User:** Rejected the `cli.py` write, then said: "Revert any changes made to career-ops. And also i am asking to create a new code repo for a for project i am going to work on, just an empty repo i can upload to github and later use to work on"
- **Changed:** The scaffolded files were deleted, leaving an empty git repo. No files in the career-ops directory had been modified (checked with `git status` and a find for files changed in the last 30 minutes), so nothing needed reverting there. The user then created the GitHub remote themselves.
- **Lesson:** "Create a repo" meant an empty repo, not a guessed implementation. Confirm scope before generating code.

## 2026-10-10 — M0 — self-caught: Python version

- **Detected:** The project requires Python 3.11+. The machine has only `/usr/bin/python3` = Python 3.9.6 (`python3.11`/`3.12`/`3.13` not found). This was raised as a decision for the user instead of installing anything.

## 2026-10-10 — M0 — Redirect: stay on Python 3.9

- **Proposed:** The AI recommended installing Python 3.12 (option 1) to keep the spec's TOML allowlist, since `tomllib` is 3.11+ only. The alternatives offered were: 3.9 + JSON allowlist (option 2), or 3.9 + a hand-written TOML subset parser (option 3).
- **User:** First asked "For d1 is oython 3.11+ that important for the project to run, if not dont. need it", then: "follow option 2 dont need to complciate it"
- **Changed:** The target is now Python 3.9+. The SKILL.md allowlist becomes a fenced JSON block (stdlib `json`) instead of TOML, which departs from the original spec. 3.9 compatibility rules were added to CLAUDE.md. PROPOSAL.md was updated (data flow, module notes, SKILL outline, R1, R3, M8, and a new Decisions table).
