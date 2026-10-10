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

## 2026-10-10 — M0 Rev 2 — Redirect: seed-driven flow + per-component error definitions

- **Proposed (Rev 1):**
  - Fan out across four sources (app, upstream HTTP dependency, Kafka, DB logs + DB server config) in a fixed order.
  - "Error" defined only generically: log level ERROR/CRITICAL, plus named detectors.
  - The LLM decided what to fetch next, guided by SKILL.md.
- **User:** "Are you defiing what an error is w.r.t each components, the components here are kafka logs, application logs, application config, db logs. The order should be that first you will give be given application log with the errros message than contains the application name, you have to go the config files for that application for which you have access and then go the kafka outputs/inputs to the applications, fetch the logs from kafka upstream downstram, related application logs using a common identifer and thread numbers and also if any downstream db is present that logs as well. This si the flow, modify the design accordingly"
- **Answer to the question:** No. Rev 1 had no per-component error definition. That was a gap in the design.
- **Changed:** Wrote `docs/design/PROPOSAL_REV2_DRAFT.md`:
  - The flow is seed-driven: seed app log → app config → Kafka in/out → related apps → DB.
  - Per-component error tables: ERROR/SYMPTOM/CONTEXT/ANOMALY with `error_code`s.
  - Thread-segment linking (app + instance scoped).
  - A deterministic traversal planner.
  - Revised models, scenarios, SKILL outline, risks R12–R16, and milestones M2–M14.
  - New open decisions D13–D20 and Q1.
- **Process note:** The user's message said "Changed somethings to the design plan", but no file changes existed on disk or on GitHub at first. While the AI was preparing the rewrite, the user edited `PROPOSAL.md` at 10:48 (removed "data-quality issues" from the bundle description). The AI's full-file write was rejected because the file had changed since it was read. Rather than overwrite a file the user was actively editing, Rev 2 went into a separate draft file. The user's edit was left uncommitted and untouched, and a snapshot was kept in the session scratchpad.

## 2026-10-10 — M0 Rev 2 — User decisions that changed the AI's proposals

User: "Q1. Data quality issues dont need it.  D13 partner pricing upstream is kafaka events,  D14 yes. D15 only one way upstreama nd downstram. D16 yes, D17 for application logs keep it 1 min. D18 is fine. D19 yes app log is given as agents first message. Dont need to check for config change histroy"

| # | AI proposed | User decided | What changed |
|---|---|---|---|
| Q1 | Keep `parse_issues` + the `data_quality` factor | Not needed | Removed from the bundle and confidence factors. Parsers still skip malformed lines (engineering rule); the parser return value is kept for tests only |
| D13 | `partner-pricing` = an external HTTP dependency seen only via app logs | It's an upstream **Kafka** producer | `partner-pricing` becomes an app with its own logs. Scenario 1 was reworked around a new topic `pricing.events` (the AI's proposal, not yet confirmed) |
| D15 | 1 hop each way, configurable up to 2 | Only one hop up and down | Fixed at exactly 1, not configurable |
| D17 | Segment ends at a different correlation ID or a gap > skew tolerance | 1-min window for app logs | A 1-min window. The AI kept "stops early at a different correlation ID" since it wasn't rejected; flagged to the user |
| D19 | `--seed-file` or first message | First message | The seed is the agent's first message. The AI added R17 (how the seed reaches the planner without the LLM retyping it) |
| D20 | `mocklogs config history` for `config.recent_change` | Not needed | Command and rule removed. Scenario 2 is rebuilt on `config.inconsistent`. Added R18 |
| D14, D16, D18 | as proposed | Accepted | — |

## 2026-10-10 — M0 Rev 2 — Scope addition: Kafka auth via the user's SSO

- **Before:** The design had no authentication model for fetching Kafka data. Access was a mock access list only (D16).
- **User:** "For traversal to fetch the kafka logs, take user sso for authentication as there is no agent login credentials vaialbel." (sent after interrupting a first version: "For traversal to fetch the kafka logs, take user as authenticator. user sso as there is no agent login vailaable.")
- **Changed:** Added D21, PROPOSAL §1.2, R19 and `CoverageGap.auth_required`:
  - Kafka commands run under the user's SSO session;
  - only the user runs `mocklogs sso login` (excluded from the agent allowlist);
  - an expired session means the agent stops and asks the user; if declined, it's a coverage gap;
  - the session marker never appears in outputs or transcripts.
  M2 and M10 scope were updated in MILESTONES.md.
- **AI's own call, flagged to the user:** SSO is applied to Kafka only, as stated. The AI asked whether app logs, config and DB logs should also require it.

## 2026-10-10 — M0 Rev 2 — SSO scope widened to all components

- **AI asked:** whether SSO should apply only to Kafka (as first stated) or also to app logs, config and DB logs.
- **User:** "Yes" (to the SSO question).
- **Changed:** D21 and §1.2 now cover every `mocklogs` fetch command. The SKILL outline and M2 scope were updated to match.

## 2026-10-10 — M1 update — AI judgment calls beyond the written §3.1 (flagged to the user)

- **`service` → `app`:** §3.1 said Event gains `app`. The AI **replaced** M1's `service` field instead of keeping both, to avoid two names for the same thing. Recorded in PROPOSAL §3.1.
- **Added invariants that weren't in the design:**
  - `error_code` is set exactly when severity ≠ CONTEXT;
  - ANOMALY only on `APP_CONFIG` records;
  - `thread` requires `app` + `instance` (enforces R12 at the type level);
  - `FetchPlan(done=True)` needs a `stop_reason`;
  - `Seed` must name the app and use UTC.
- **New small types not named in §3.1:** `TopicSubscription` (instead of a `(topic, group)` tuple, for readable JSON), the `Direction`/`GapReason`/`FactorName` enums, and the `THREAD_SEGMENT_WINDOW_MS` constant.
- **Self-caught:** a garbled test comment ("ID-less of thread is fine") was fixed before committing.
