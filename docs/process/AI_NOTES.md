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

## 2026-10-10 — M0 — Rejected suggestion: skew tolerance

- **Proposed:** A default clock-skew tolerance of 2000 ms (D2), configurable per source.
- **User:** "D2 keep thje clock skew tolereance as 1 min because we have seen kafak events reflected after a 1 min, we will keep 1 min than we will tune it"
- **Changed:** The default is now 60 000 ms, to be tuned later. The AI raised one concern and recorded it as risk R6b in PROPOSAL.md: a 1-min tolerance makes cross-source events under 1 min apart order-uncertain unless they share an ID, and a Kafka delivery delay is not the same as clock skew. Mitigation: causal order within an ID chain overrides timestamps, and the bundle reports an order-uncertain count to guide tuning. The user's decision stands.

## 2026-10-10 — M0 — Rejected suggestion: validator retry limit

- **Proposed:** D12: at most 2 retries when the validator rejects a report, then fall back to INSUFFICIENT.
- **User:** "for d12 keep it 3 we will tune it later based on data"
- **Changed:** The retry limit is 3, to be tuned from run data. PROPOSAL.md D12 and R7 were updated.

## 2026-10-10 — M0 — self-caught: editable install won't work on system pip

- **Detected:** While recording D9 (pyproject + setuptools), a check showed the system has pip 21.2.4 and setuptools 58.0.4. An editable install of a pyproject-only project needs pip ≥ 21.3 and setuptools ≥ 64, so D9 as proposed would fail on the system Python. The AI had not checked this before recommending D9.
- **Changed:** Added risk R11, which proposes a project-local `.venv` with upgraded pip/setuptools plus pytest. This is pending the user's OK.

## 2026-10-10 — M0 — self-caught: table ordering slip

- **Detected:** R11 was first inserted before R7 in the PROPOSAL.md risk table by a string-insert script. It was moved after R10 before committing.

## 2026-10-10 — M0 — self-caught: wrong commit count

- **Detected:** The AI told the user there were "12 local commits" to push. A `git log --oneline | wc -l` run afterwards showed 11 before entry 010's commit (12 including it). The count had been stated without checking. It was corrected in the next reply.

## 2026-10-10 — M1 — self-caught: shell exit-code check didn't work

- **Detected:** The command that ran `pip install -e .` printed its exit code with `${PIPESTATUS[0]}`, which is bash-only. The shell is zsh, so it printed an empty value. Success was confirmed separately with `pip show` (editable location = project root) and by the imports resolving to `src/`.
