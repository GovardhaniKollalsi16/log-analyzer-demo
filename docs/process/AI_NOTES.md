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

## 2026-10-10 — M2 — Redirect: write the skill earlier

- **Proposed (Rev 2 plan):** SKILL.md only in M10, together with the allowlist. Upstream/downstream discovery lived only in the M5 planner code.
- **User:** asked "in which step are you creating skill files for the agent to know how to connect to neach log source and how the agent will know to fetch the applicationn up streama dn downstream systems. In what step are we creating the skills that is important". After the AI proposed staging it, the user said: "Yes, move skills earlier and start M2 with SKILL.md"
- **Changed:**
  - **v0 in M2,** written *before* `mocklogs` as the agent-facing contract for the commands;
  - **v1 in M5:** traversal (upstream via headers, downstream via consumer groups, following `investigator plan`);
  - **v2 in M10:** allowlist + report contract.
  MILESTONES.md and PROPOSAL.md §5/§7 updated.
- **AI's assessment:** having the skill only in M10 was a planning weakness. The skill is how the agent learns to reach each source, and it was scheduled after the code it describes.

## 2026-10-10 — M2 step 1 — self-caught: SKILL.md examples leaked scenario answers

- **Mistake:** The first SKILL.md v0 draft used scenario 1's real names and failure chain as its output examples: an `order-api` "Timed out waiting for pricing event" error, and `partner-pricing` producer `REQUEST_TIMED_OUT` retries on `pricing.events`. It also used a scenario 2 DB "statement timeout" line. The agent reads the skill, so this would have hinted the root causes and undermined the "never hardcode a root cause" rule.
- **Caught:** On re-reading the draft before showing it to the user.
- **Fixed:**
  - All examples replaced with neutral `example-*` values and benign lines.
  - Added `tests/unit/test_skill_neutrality.py`, which fails if SKILL.md mentions scenario vocabulary. Canary check: appending "order-api" made it fail; removing it made it pass.
  - Moved the shared vocabulary list into `tests/unit/_vocabulary.py`.
  - Added risk R20.

## 2026-10-10 — M2 step 1 — Redirect: one skill per component

- **Proposed:** a single `incident-logs` SKILL.md v0 covering all four components.
- **User:** "I think it is better ton have skills for each component seperately on how to login and what to looks and command to search based on time, cluster, topic. for kafaka like wise for others, create sperate skills files"
- **Changed:**
  - Four component skills plus `incident-logs` kept as a slim coordinator. Keeping a coordinator was the AI's choice: the order, the hard rules, and "which skill when" don't belong to any one component. Flagged to the user for review.
  - The neutrality guard was extended to every skill (canary on `incident-kafka` failed with `pricing.events`, then passed after restoring).
- **New assumptions the AI introduced, flagged for review:**
  - cluster/namespace now come from the seed line;
  - related apps are assumed to be in the seed's cluster (R21);
  - a default time window of −10/+2 min;
  - Kafka time search via `kafka-get-offsets`;
  - a model follow-up for `cluster`/`namespace`, deferred to M3.
- **Gap the AI found:** the user's request for search "based on ... cluster" exposed that the design had no cluster dimension at all. Neither the models nor the commands named a cluster.

## 2026-10-10 — M2 step 1 — Redirect: inputs come from the incident; "no input, no access"

- **Before:** The skills derived Kafka cluster/topics and the DB host from the seed app's **config**, and assumed related apps run in the seed's cluster (R21, the AI's own assumption).
- **User:** "I need ton add afeguards and limiting but will add later. The incident will mention the what will be inouts for each siource, i.e. we need kafka server cluster and topic and for each db same as well. Make it cler in the skills what is the inouts required to execute the skills, if the required inout is not present we will not try to access the logs."
- **Changed:**
  - Every component skill has a "Required inputs" table and a don't-run-if-missing rule (→ `missing_input` gap).
  - The coordinator has rule 1 "No input, no access" and a proposed `INCIDENT` format.
  - The config was demoted to direction/group/limits only.
  - R21 withdrawn.
  - D22 recorded; D23 (incident format) proposed; D24 (safeguards/limiting) deferred to the user and kept out of scope.
- **Self-caught:**
  1. After the section swap, the `incident-app-config` "what to read" table and Forbidden note, and the `incident-db-logs`/`incident-kafka`/`incident-app-logs` descriptions, still said inputs came from the config. Found by grep and fixed.
  2. The structure test still required the old "Where the inputs come from" heading. 4 tests failed (`4 failed, 34 passed`) until the test was updated to the new rule. The failure was expected from the heading change, but the AI ran the tests before updating them.
- **AI interpretations flagged to the user, not yet confirmed:**
  - the plain `app:` line covers only the seed app, so related apps need `app[<name>]:`;
  - the config may still supply the consumer group and the consume/produce direction.

## 2026-10-10 — M2 — Interpretation: skills approval settles the two open points

- **Context:** The AI had asked two questions: does `app:` cover only the seed app, and may the config supply topic direction and group? The user didn't answer them directly and said "nice the skills are fine now. commit and goahead with next steps".
- **AI's interpretation:** Approval of the skills as written, which already encoded (a) seed-app-only `app:` and (b) config for direction/group. The markers were removed, and the user was told explicitly so they can object.

## 2026-10-10 — M2 step 2 — self-caught issues while building mocklogs

1. **Private-attribute hack:** the first generator draft set `world._seed_record` on a dataclass. It was replaced with a proper `Incident.seed_record` field before any test ran.
2. **Dead code:** the first `cli.run()` draft had a leftover `if key != "scenario" or True: pass` and a muddled type conversion. Rewritten before the first run.
3. **Banner after the error:** the first manual run of a refused command printed the error *before* the MOCK banner (stdout is buffered, stderr isn't). Fixed with an explicit flush; re-run showed the correct order.
4. **Rename leak (caught by a test):** `test_rename_knob_removes_every_default_name` failed with `'order-api' is contained here: ... group=order-api-pricing`. Composite names (consumer groups, DB user) had the app name baked in, so renaming the app left the old name visible. That would have defeated the robustness renames. Fixed by deriving composite names from their parts after renames. Re-run: `83 passed`.

**AI design choices in mocklogs, flagged to the user for review:**
- `kubectl logs deploy/<app>` merges all pods (real kubectl picks one pod unless told otherwise).
- Exit codes 5 (not found/unreachable) and 6 (no scenario) aren't in the skills yet.
- The upstream producer's retry/expiry lines are on Kafka's network thread, so they link to the request by partition and time, not by thread.
- Kafka's internal "correlation id 8850" request number appears in producer logs; it's unrelated to the app correlation ID (a deliberate realism trap for the parser).

## 2026-10-10 — M2 — Correction: one correlation ID across services was wrong

- **What the AI had built:** the skills told the agent to follow the seed's `correlation_id` into Kafka, related apps and the DB. The scenario 1 mock data used **one** correlation ID for an order in every app and in the Kafka headers.
- **User:** "So Correleantion ID is only for in app logs search, For different upstreams and different sub services inside in the service it has different correleation id accross distributed systems." / "Int he cindident management add a section which id to use to correate based on different api's. I will Give a list." / "for order based service it is OrderId. For now if the error Log is from Order* file, fetch the order_id from the log and use it to correlate and if The log is from Product* the correlation shoudl be product id. In kafka and db logs the product id is stored in product_id and order_id is stored in order_id. This is imoportant correlation"
- **Changed:**
  - Design: D25 + §1.0 + risk R22 (business keys aren't request-unique) + M3 model follow-up (`Event.keys`, `LinkKind.BUSINESS_KEY`).
  - Skills: a correlation-key table in the coordinator; business-key searches in the app-logs, Kafka and DB skills.
  - Mock data: per-app correlation IDs; the seed now logs from an `Order*` class with `order_id`; Kafka values carry `order_id` + `product_id`; the header `correlation_id` is the producer's own; DB statements carry both keys; three products shared across ten orders.
  - The old ground-truth test (which assumed a shared correlation ID) failed as expected: `assert False` on the upstream-correlation check. It was rewritten, and 6 tests were added → `89 passed`.
- **AI's own assessment:** the shared-ID assumption came from the original spec wording ("correlates logs by correlation/trace/message ID") and was never challenged. It's realistic only inside one service.
- **Interpretations flagged to the user:**
  - "Order* file" was taken as the record's **source class**, i.e. the last segment of `logger` (the mock has no separate `file` field);
  - the user's "Yes" to "do these formats look like work? Do any … resemble your employer's systems?" answers two questions at once, so the AI asked which one it meant before treating it as resolved.

## 2026-10-10 — M2 — Domain clarification: OrderService / ProductService

- **User:** "Yes, one more thing For All product based inpusts comes from Product Service and Orders come from OrderService and it has logs of the whichbwill have the order_id and the the correlation id in app should/will match it"
- **AI's interpretation:**
  - "Order* file" refers to the OrderService and "Product*" to the ProductService;
  - pricing is a product-based input, so the upstream app is the ProductService;
  - "correlation id in app should/will match" means one correlation ID per order within a service. The mock already did this; it's now pinned by a test.
- **Changed:** mock seed app `order-api` → `order-service` (classes `orders.Order*`); upstream `partner-pricing` → `product-service` (classes `products.ProductPrice*`); coordinator skill domain note; D25a; vocabulary guard updated; new test → `90 passed`.
- **Still ambiguous, asked again:** the user's "Yes" didn't say which of the two questions it answered (realistic formats vs. resembling the employer's systems). Until it's answered, nothing gets pushed.

## 2026-10-10 — M2 close-out — self-caught: sample regex missed indented blocks

- **Detected:** After the first `python -m mocklogs.skill_samples --write`, `grep -c PENDING` still found placeholders (2–3 per component skill). The marker regex only matched unindented blocks; the refusal samples sit inside list items and are indented.
- **Fixed:** The regex now captures the indentation and re-indents the generated body. Second `--write` → 0 placeholders; `--check` → exit 0.
- **Also:** a stray `tests/.DS_Store` (macOS metadata) appeared untracked. It was deleted and `.DS_Store` gitignored.
- **AI design note:** samples come from the scenario 1 world with every name overridden. To stop real scenario content from leaking through a future sample choice, a story-phrase guard (e.g. "Shrinking ISR from", "REQUEST_TIMED_OUT") now fails if such text appears in any skill. Canary-tested.

## 2026-10-10 — M3 — self-caught issues

1. **Dead/odd code removed before testing:** an unused `at()` helper in `normalize.py`, a junk `__all__ = {}` in `parsing/dispatch.py`, and a stray `Level` import/export in `parsing/app_logs.py`.
2. **Dedupe counting bug (found in review, before tests):** the first `dedupe.py` counted occurrences per command string, so re-running the *same* command would have been reported as duplicates. It now counts distinct line numbers per command: repeats inside one output count, reruns don't.
3. **Mock bug (found by the new integration test):** perturbation knobs shuffled/duplicated lines *inside* structured outputs. The multi-line configmap JSON became invalid (7 config events missing, 2 malformed issues), and lag-table headers could move. Real tools never do this, so structured outputs (configmap, consumer-group tables, offsets) are now exempt. Test added.
4. **Flaky test → mock determinism bug:** the full suite passed 2 of 3 runs. The noise seed stripped the `--save-dir` flag but not its path value, so every test's temp directory changed the "random" noise. Fixed (`argv_without_save_dir`); test added; 5/5 runs → `179 passed`.
5. **Two wrong test assumptions (AI's tests, not code):**
   - The lag test expected only samples {1,2,3}, but the `--all-groups` snapshot legitimately adds untimed rows (`None`).
   - The "nothing invented" assertion was too strict: a truncated plain-text DB line still parses, since it can't reveal it was cut. The rule is now that an unknown event must be a prefix of a real line.

## 2026-10-10 — M3 — Fix: ts_raw wasn't verbatim (AI-found, user-approved fix)

- **Found by:** the M3 demo the user asked for. For Kafka messages and lag rows, `ts_raw` held a reconstructed ISO string (`2026-03-14T09:00:20.300000+00:00`) instead of what the tool printed (`1773478820300` after `CreateTime:`, or the `# sample … at` header value).
- **User:** "Fix this and proceed to M3"
- **Changed:** `parsing/kafka.py` now keeps the printed text in `ts_raw`. New test `test_ts_raw_is_always_verbatim` (canary: restoring the old line made it fail; restored → `180 passed`).
- **Open question left unanswered:** whether a Kafka client ID like `product-service-producer-1` may be mapped to an app by prefix. Kept strict (no mapping) until the user decides.

## 2026-10-10 — Between M3/M4 — Correction: Kafka client IDs must map via config, never by name

- **AI asked:** whether `product-service-producer-1` may be attributed to `product-service` by prefix (the AI's default was strict, no mapping).
- **User:** "Dont map like that, just map kafka client details from the config you get from kubectl for the application and then get access to kafak clients. In our application in config we define upstream/downstream consumers and dbs in a config file that is accessible from kubectl config,"
- **Self-caught violations exposed by this rule** (both were the AI's own earlier choices):
  1. The `incident-kafka` skill said a consumer group's "`CLIENT-ID` is the app name", and its fallback said "treat any producer other than the seed app as upstream". Both infer apps from names or headers.
  2. M3's lag-table parser set `Event.app = CLIENT-ID`, the same guess in code. The mock also printed app names in the `CLIENT-ID` column, which hid the problem.
- **Changed:**
  - Mock: real client IDs (`<app>-producer-1` / `<app>-consumer-1`) in Kafka logs and lag tables. The seed configmap declares `upstream.apps`, `downstream.apps` and `*.kafka.client.ids`; other apps' configs declare their own IDs.
  - Parser: lag rows now have `app=None`.
  - Skills updated (see SKILL_CHANGELOG). D26 recorded; R13 superseded; M5 scope gains the config-based client-ID map.
  - Snapshots regenerated (diff reviewed: only config keys, client IDs and the `CLIENT-ID` column changed). 3 tests added → `183 passed`.
- **Open:** the user also said DBs are defined in the config. Under D22 the DB step's inputs come from the incident. The AI asked whether the config may also supply DB/related-app access inputs.

## 2026-10-10 — M4 step 1 — self-caught issues while writing the rule tables

1. **Overfitting risk:** the AI writes these rules after having seen scenario 1's text. One app rule, `no \S+ event within`, was shaped like scenario 1's own error message ("no pricing event within 30000 ms"). It was removed before the first run. Remaining mitigations: the rules follow PROPOSAL §2 (written before any data existed), and the M8 robustness matrix plus scenarios 2–4 will test them on data they weren't written against. The broker rule `timed out waiting for in-sync replicas` matches the mock's own invented wording (real Kafka says `NOT_ENOUGH_REPLICAS`); both patterns are kept, and this is flagged to the user.
2. **Rule order:** in the first run, the app line "Failed to publish pricing event…" classified as `app.retries_exhausted`, because its error detail says "Expiring 1 record" and that rule came first. `app.publish_failed` now comes first, with a comment explaining why.
3. **Demo bug (AI's scratch script, not product code):** the hand-written config sample used a shortened banner (`# MOCK`), so it parsed as malformed JSON and printed nothing. Fixed the script; the config rules then worked.
4. **Observed, not fixed (M6 concern):** the producer client's retry/expire lines exist in two sources (the upstream app's JSON logs and `kafka logs --component producer`), so one occurrence is classified twice (`app.retry_attempt` + `kafka.producer.retry`). Cross-source duplicates should be linked in M6, so detectors don't double-count. Flagged to the user.

## 2026-10-10 — M4 review — Redirect: collect first, assess later; narrower Kafka scope

- **AI proposed:** M4 rule tables classifying every record as ERROR/SYMPTOM/CONTEXT/ANOMALY. The Kafka skill also had the agent check consumer-group lag and list all groups, with a "what to look for" list of signals.
- **User:** (pasted three of the AI's severity rows, then) "The llm assesing what is wrong with the log comes after for now we need to collect logs for all related events and then we can debug. In kafka check incoming, outgoing and any retires logs. that is all. but also for kafka any topic that error, connection timedout related to the topic should be of concern. Edit skills file accordingly."
- **Changed:**
  - Coordinator rule 0, "Collect first, assess later".
  - Kafka skill rewritten around four collections per incident topic; lag/all-groups removed; checklist instead of judgement cues.
  - D28 recorded; M5 planner scope updated.
  - Test added → `184 passed`.
- **Self-caught while editing:** the new §3 heading broke the cross-skill structure test (`## 3. Command…` prefix), and one stale "(lag and logs still run)" remained. Both fixed.
- **Open questions raised with the user (the AI didn't decide them):**
  1. The original brief's scenario 3 is "Kafka consumer lag/processing failure → downstream symptoms". Without lag collection, the lag half of it can't be observed; processing failures still show in consumer logs. Keep lag for scenario 3, or redefine the scenario?
  2. Does "assessment comes after" mean M4 (deterministic classification) should be parked, so the next step is the M5 collection planner? Or should M4's tests be finished first?

## 2026-10-10 — M4 step 2 — tests exposed a real rule gap (+ one test bug)

- **Interpretation:** the user said "finish M4" without answering the four step-1 review points. The AI treated the rule tables as approved as written: the transient-exception downgrade stays proposed for M7, and the mock-wording broker pattern is kept alongside the real one. Flagged in the reply.
- **Real bug found by the tests:** `kafka.broker.request_failed` used `notenoughreplicas`, which matches the exception class `NotEnoughReplicasException` but **not** real Kafka's error code `NOT_ENOUGH_REPLICAS`. The rule caught the mock's invented wording but missed the real one, which is the overfitting risk flagged in step 1. Fixed to `not_?enough_?replicas`.
- **Test bug (AI's):** the config test helper `cfg()` contained a half-written leftover expression passing `ts_utc` twice (5 TypeErrors). Rewritten.
- **Result:** `tests/unit/test_classify.py` 66 passed; the integration test (scenario 1 + rename invariance) 2 passed; full suite 3 runs → `252 passed`.

## 2026-10-10 — M5 — self-caught issues

1. **Junk code before the first run:** `planner.py` ended with a meaningless `_unused: Set[str] = set()` and an odd `__all__`, and `run()` recomputed the config status that `seed_config()` already knew. Removed and simplified (`seed_config` now returns `(topology, settled)`).
2. **Walkthrough script bug (scratch, not product):** the subprocesses couldn't find `mocklogs` because the venv `bin` wasn't on `PATH` (`FileNotFoundError`). Fixed in the script.
3. **Misleading label:** in round 1, offsets steps said "direction unknown" because the config wasn't read yet in that same round. The label was dropped from the offsets step; message steps (round 2) are labeled correctly.
4. **Weak test assertion:** the config-denied test accepted any message step (`… or "messages on" in r`). It now asserts every message step is labeled "direction unknown". Canary: forcing "incoming" made it fail.
- **Still open (R17):** how the incident gets into `<workdir>/incident.txt` in the Claude Code subagent path. The Python loop (M11) writes it directly; the subagent mechanism is decided in M13.

## 2026-10-10 — M6 — what the skew demo exposed, and self-caught issues

1. **Collection gap (found by the demo the M6 plan asked for):** with 45 s Kafka skew injected, the timeline placed the upstream producer's retries **after** the seed error (they were flagged order-uncertain, but uncorrected). Root cause: the planner never fetched `product-service`'s Kafka network-thread lines (no business key, no correlation ID, different thread), so there were 0 same-occurrence pairs and skew couldn't be measured. **Fix:** the planner fetches each app's logs by the Kafka client IDs the seed config declares (D26). Result: 8 pairs, +45000 ms measured exactly.
2. **Wrong reference clock (also found by the demo):** the first correction used Kafka (the busiest clock) as the reference, shifting the app forward 45 s onto Kafka's skewed time. Only relative offsets are measurable, so the reference is an assumption. It now prefers the seed's clock, then an app clock (R25). With that, the true order came out: ISR shrink 09:01:50 → retries → expiry → publish failed → seed 09:04:50.
3. **Junk code:** `timeline.py`'s first draft had a loop ending in `pass` and an over-complicated sample count. Removed before the first run.
4. **Canary checks:** disabling the "thread switched request" rule failed the interleaving test, and estimating skew from ID links failed the delivery-delay test. Both restored.
5. **Not implemented, said openly:** the design's "causal order within an ID chain overrides timestamps" (R26). Ordering is skew-adjusted time plus uncertainty flags.

## 2026-10-10 — M6 — Redirect: drop all clock-drift/skew handling (D30)

- **AI had built (M6):** skew estimation from same-occurrence pairs, reference-clock selection (R25), skew-adjusted ordering, `order_uncertain`/`concurrent_with` flags with a 60 s tolerance (D2), a mock skew knob, and a deferred "causal reordering" item (R26). The AI had treated drift as a first-class problem since M0.
- **User:** "Yeah the clock drift between machines is not an issue, since the window is big. Ignore all the references in the application that measure or take into account clock drift/skew"
- **Changed:**
  - `investigator`:
    - `timeline.py` now sorts by UTC timestamp with deterministic ties;
    - `SkewEstimate`, `DEFAULT_SKEW_TOLERANCE_MS`, `TimelineEntry.adjusted_ts/skew_applied_ms/order_uncertain/concurrent_with` and the bundle's skew fields are removed;
    - the same-occurrence match window went from 1 min to 2 s (copies of one line are written moments apart).
  - `mocklogs`: the `skew_ms` knob and `render.skewed` are removed. Snapshots and skill samples were unchanged, which confirms the knob never affected default output.
  - Skills: coordinator rule 4 and the Kafka timing sentence no longer mention skew.
  - `CLAUDE.md`: the user's original rule "handle … timestamp skew" was updated to record D30. This is the user's own rule changing; the AI changed only the wording to match the decision.
  - Design: D2 superseded; R6/R6b/R25/R26 withdrawn; module, model and milestone text updated; the M8 matrix loses "skew below tolerance".
  - Tests: skew-specific tests removed or replaced by plain chronology tests → `282 passed`.
- **Kept on purpose, flagged to the user:**
  - the 1-minute **thread** window (D17), which groups one unit of work on a thread and isn't a clock allowance;
  - SAME_OCCURRENCE links, which still stop a Kafka line being counted twice;
  - the planner's client-ID fetch, which still collects the app-side retries.
- **Self-caught:** a guard in the AI's own edit script rejected its replacement comment (which contained "skew") and stopped the script half-way. It was rerun after rewording.

## 2026-10-10 — M7 — issues found while implementing the approved rules

1. **Spec typo (AI's, in the approved M7_RULES):** the coverage row said a gap on a DB the seed config "doesn't declare" is PARTIAL, which contradicted the doc's own relevant-gap definition. Corrected to "declares" in the file, with an inline note, before coding. It was not silently coded differently.
2. **Sloppy code caught before running:**
   - `Hypothesis.ceiling` defaulted to `None` with a type-ignore; it now defaults to `INSUFFICIENT`, the safe value.
   - The detectors module ended with `_ = timedelta` (to keep an import alive) and had an unused `_ts` helper. Both removed.
   - `relevant_gaps` took an unused `incident` parameter. Removed.
3. **Design flaw found by the demo:** with degraded collection (config denied / related lines omitted), the two retry-exhaustion findings on the **same** producer (orders o-1005 and o-1008) formed two chains and counted as each other's "equally strong rival", so `competing_hypotheses` came out WEAK. Fix: findings from one detector on the same client/resource merge into one chain. After the fix, each variant has one hypothesis; the ceilings are unchanged (HIGH / LOW / LOW, matching the hand-computed expectations in M7_RULES §4).
4. **Test bug (AI's):** a D-6 test passed `code=` twice through the `SEED()` helper and then patched the event with a second constructor call. Rewritten.
5. **Kept as an open decision:** the "transient exception" rule wasn't answered and isn't in the approved file, so it's **not** implemented.

## 2026-10-10 — M8 — Redirect: the AI must investigate, not just narrate (D31)

- **User (asking, with "dont change anyhting"):** "is this an ai first appliction or is this a normal applciation that is using ai very lgihtly"
- **AI's honest answer:** as designed, it's deterministic-first. Code decides the fetches (planner), the errors (M4), the patterns and candidate causes (M7) and the confidence; the AI only picks among candidates and writes. Part of that came from the brief ("the LLM never parses raw logs or decides chronology"), but the AI pushed further than required: the deterministic planner (D18) was its own proposal, and it repeatedly moved judgment into code.
- **User:** "Yes AI should do the investigations but not be a just the narraotr. what can we change simply to make it possible" → after the AI's proposal: "Yes that makes sense continue"
- **Changed (design only so far):**
  - D31 recorded; D18 amended (planner = suggestions).
  - New milestone M8b (`investigator check` guard + `investigator score --cause`).
  - M9/M10/M11 scope amended.
  - M8 continues unchanged.

## 2026-10-10 — M8 — what running scenarios 2–4 exposed

1. **Collection gap (planner, AI's):** the DB step searched only by business key, so connection errors (`FATAL: too many clients`), which carry no order ID, were never fetched and the DB-burst detector couldn't fire. This is the same class of gap as the Kafka client lines in M6. Fix: the DB step also fetches the seed app's own sessions.
2. **M7 detector bug (AI's):** `poison_message` iterated over events with same-occurrence copies removed, but the Kafka-side copies are the only lines carrying topic/partition/offset, so scenario 3 found no poison and ended INSUFFICIENT. Fix: read Kafka-side lines; each occurrence is still counted once.
3. **Bundle bug (found as a `KeyError` in the AI's demo):** a hypothesis cause could be a cited copy, which the bundle excluded. Fix: drop copies unless cited.
4. **Scenario 4 knob bug (AI's, caught on re-read):** the "seed config denied" default was replaced, not extended, when a test passed other denials. It's now always included; test added.
5. **Shell slip (demo only):** an unquoted `$W` holding two flags isn't word-split in zsh, so the sample command failed. Rerun with explicit args.
6. **Matrix verified by canary:** planting a topic-name dependence in the poison detector made exactly `consumer-processing × rename` fail (HIGH → INSUFFICIENT). Restored.
- **Design note:** scenarios 2–4 use a new shared `builder.py`. Scenario 1 keeps its own code so its approved snapshots can't drift; the duplication is known and accepted.
- **Outcome:** all four scenarios give their intended result (HIGH / HIGH / HIGH / INSUFFICIENT) under every perturbation; access denials lower confidence in all three applicable scenarios.

## 2026-10-10 — M8b — guardrails built ("Start with your guardrails i will fix it later")

- **Built:**
  - `investigator check` (`guard.py`): command shape + documented flags; shell metacharacters; `--save-dir` = workdir; WHERE from the incident (D22/D27); WHO from the seed config (D26); only the seed config is readable; consumer-group lag out of scope (D28/D29); `sso`/`scenario` refused. Reasons are machine-readable codes.
  - `investigator score --cause` (`analysis.score_cause`, `pipeline.prepare/score_in_workdir`): the M7 factors and ceiling for any parsed event. Effects = the seed; rivals = detector hypotheses with a different cause.
- **Key consistency test:** every planner step passes the guard in all 4 scenarios.
- **Self-caught:** a score test assumed a seed-app "Health check OK" line was collected. It isn't: the planner fetches the seed app by correlation ID, so the test got `StopIteration`. Changed to a collected-but-unrelated event (a consumer's "Subscribed to topic" line).
- **Canary:** disabling the "app must be declared in the seed config" rule failed 2 guard tests; restored.
- **Known gaps left for the user to tune ("i will fix it later"):**
  - no time-window bounds on AI commands (the AI can request any window), which overlaps D24 rate limiting;
  - `--grep` values aren't restricted;
  - the guard isn't yet wired into the skills (M10) or the runner/hook (M11/M13). Until then it's a callable check, not an enforced one.

## 2026-10-10 — M9 — notes

- **Design choices the AI made (flagged to the user):**
  - Citations may point at **any collected event**, not only the bundle subset, so an investigating AI (D31) can cite what it fetched itself.
  - The report must restate the computed factor **values** exactly (`factors_mismatch`); only the reasons may be reworded.
  - Every coverage gap must be acknowledged in `gaps`.
  - A named cause with INSUFFICIENT is rejected as a contradiction; "unknown" is the honest form.
  - `fallback_report` keeps the detector leads as **open** alternatives instead of discarding them.
- **Self-caught:** a pointless f-string in the renderer and an unused `first_error_summary` helper were removed before the tests. One test assertion was again too weak (`… or ceiling is INSUFFICIENT`); it now asserts the exact error set for each case.
- **Canary:** disabling gap acknowledgement failed exactly `gap_not_acknowledged`; restored.

## 2026-10-10 — M10 — notes

- **Design choices the AI made (flagged to the user):**
  - The allowlist moved from constants in `guard.py` into the skills (single source of truth). Otherwise the skills and the guard could drift apart.
  - `investigator run` is the **only** way the agent fetches, and `--reason` is mandatory. Every attempt goes to `actions.jsonl`, which is the record of the AI's investigative decisions.
  - R17 resolved with `investigator init --incident-file`. For the subagent path, the user hands over a file path.
- **Self-caught:**
  1. An old skill test pinned "exactly as given, in order", correctly failing once D31 replaced that procedure. Updated to pin the new procedure.
  2. Two bugs in the AI's new tests: one treated a code block with two commands as a single command, and one expected a MOCK banner that the in-process `run()` doesn't add. Then a sloppy patch to the first left junk (an `_unused()` function, `if True:`, misplaced counters). It was rewritten cleanly instead of patched again.
- **Canary:** removing `--thread` from the app-logs allowlist failed the documented-commands test; restored.

## 2026-10-11 — M11 — what building the agent loop exposed

1. **Analysis crash with nothing fetched (found by the turn-budget test):** the fallback after zero fetches raised `KeyError` on the seed event ID, because the analysis assumed the seed's log line had been collected. Fix: the incident's seed event is always included (it is evidence in its own right).
2. **Process-rule slip (the AI's):** the first manual fake run wrote its transcript to the scratchpad, not `runs/`. It was copied into `runs/` afterwards.
3. **Scenario-name leak (the AI's demo setup):** the demo workdirs were named `work-<scenario>`. The workdir path is in the model's first message and in every `--save-dir`, so every model-visible transcript entry named the scenario. Caught by a leak check before committing. The flawed runs are kept (never-delete rule) and documented in `runs/README.md`; clean reruns use `case-N`. New risk R27, plus a leak test (canary: scenario-named workdirs failed all 4 cases).
4. **Sloppiness caught before running:** the fake set an undeclared `own_cause_overclaim` attribute via `getattr`. It's now a declared field.
- **Canary:** making the loop accept any submitted report failed the invented-ID and over-claim tests; restored.
- **Note:** the full suite now takes about 30 s, because the agent tests spawn real `mocklogs` subprocesses.

## 2026-10-11 — Before M12 — Redirect: use the Claude account, not an API key (D32)

- **AI had planned (D10, from the brief):** an Anthropic API provider using `ANTHROPIC_API_KEY`.
- **User:** "YEah i want this application to run with the my claude account not with api key", then "Pathj 2"
- **Interpretation (flagged):** "Pathj 2" = build the command-line path (Python launches Claude Code headless) first. Whether the interactive path (talking to the subagent in Claude Code) is still wanted will be asked at the end of M12.
- **Verified before designing, not assumed (R2):**
  - local `claude` v2.1.296 has `-p`, `--agent`, `--allowedTools`, `--output-format stream-json` and `--permission-mode`;
  - the docs (sub-agents, permissions, authentication) confirm the `skills:` frontmatter, `PreToolUse` hooks with exit 2, `Bash(investigator *)` prefix rules with compound-command splitting, `dontAsk`, `Edit(//abs/**)`, and that `-p` uses the `/login` subscription unless `ANTHROPIC_API_KEY` is set.
- **Changed:** D32 (supersedes D10); R2 resolved; M12 rescoped.

## 2026-10-11 — M12 (path 2) — Notes while building the Claude Code harness

1. **Process slip (the AI's):** while testing the hook by hand, the loop wrote stderr to `/tmp/hookerr` instead of the session scratchpad. Nothing project-related was kept there.
2. **Wrong test expectation (the AI's):** the first hook test expected the text "only `investigator`", but the hook says "only `investigator ...` commands". The test was fixed, not the hook. 3 failures, then green.
3. **Changed an existing test:** `test_cli_agent` asserted that `--provider anthropic` returns 2 ("not until M12"). Per D32 that provider no longer exists, so argparse now rejects it. The test asserts that instead.
4. **Deviations from the stated plan, flagged:**
   - The local `claude` has no `--max-turns` flag, so the turn cap is the subagent's `maxTurns: 60` plus a 20-minute process timeout.
   - The harness saves `incident.txt` itself, the same way `run_agent` does, rather than shelling out to `investigator init`. Same validation, same verbatim write.
   - Added `--setting-sources project` and `--strict-mcp-config`. Otherwise the user's own allow rules or MCP servers could widen what the subagent may do.
5. **Not yet verified against the real `claude` (R2 is still open for these):**
   - that the subagent-frontmatter hook in exec form (`args: []`) fires under `--agent`;
   - that `Edit(//<workdir>/**)` permits the Write tool in `dontAsk`;
   - that Read of `incident.txt` under `--add-dir` needs no rule.

   The fake `claude` calls the real hook, but it can't prove Claude Code calls it. The first live run will.

## 2026-10-11 — M12 — First live runs on the user's login: the hook hadn't been firing

- **Run 1** (`runs/20261011T165123162161Z-claude-code-upstream-timeout.jsonl`, scenario 1, 45 turns, 138 s, $1.07 reported by Claude Code):
  - valid report, HIGH, no fallback;
  - `apiKeySource: none`, so it ran on the login, not a key.
- **Defect 1 (the AI's, an unverified assumption from the previous note):** the hook declared in the subagent's frontmatter **did not fire**: `investigator --help` ran, and the hook should have blocked it.
  - Bash stayed limited to `investigator …` only because of the permission rule.
  - But that rule (`Bash(investigator *)`) also allowed `investigator agent`, a nested run the hook exists to stop.
  - The docs say project agent hooks need workspace trust, and they don't confirm `${CLAUDE_PROJECT_DIR}` expansion in frontmatter. The exact cause wasn't isolated.
- **Defect 2 (the AI's design gap):** Claude Code runs with the repo as its cwd, and `dontAsk` still allows reads inside the working directories. So the agent *could* read `src/mocklogs/scenarios/*`, where the answers are. It didn't, but nothing stopped it.
- **Defect 3:** the report-attempt counter counted `investigator validate --help`, so it said 2 attempts when there was 1.
- **Fixes:**
  - The permission rules are now the primary limit: one allow rule per allowed subcommand, a deny for `investigator agent`, and denied reads of `src/`, `tests/`, `docs/` and `runs/`.
  - The hook is also passed through `--settings` by absolute path.
  - `--help` calls are no longer counted.
- **Verified live** (`runs/20261011T165656Z-claude-code-guard-check.jsonl`, 5 turns, $0.05):
  - `investigator --help` and `investigator agent --help` were blocked by the hook, with its message;
  - reading `src/mocklogs/cli.py` was denied by permissions;
  - `investigator plan --help` ran.
  - The frontmatter hook is kept, but it's still unverified.
- **Note:** run 1 happened before these fixes, so it ran with the weaker limits. It's kept and documented in `runs/README.md`.
