# Skill & Subagent Changelog

Every change to `.claude/skills/incident-logs/SKILL.md` or `.claude/agents/incident-investigator.md` gets an entry here.

Format:

```
## YYYY-MM-DD — <file> — <short title>
- Reason:
- Triggering run transcript: runs/<timestamp>-<scenario>.jsonl
- Change:
```

---

## 2026-10-10 — SKILL.md — v0 created (M2 step 1)
- **Reason:** User decision to write the skill first, as the agent-facing contract for `mocklogs` ("Yes, move skills earlier and start M2 with SKILL.md").
- **Triggering run transcript:** none. No agent runs exist yet; this version comes from the design, not from an observed run.
- **Change:**
  - New file with: hard rules; authentication via the user's SSO + access refusals; the component → command map with exact syntax; illustrative output formats; the error-classification pointer; an investigation-order summary.
  - Example values are deliberately neutral (`example-app`, `example.topic`, …). The first draft reused scenario 1/2 names and failure messages, which would have hinted answers to the agent. That was caught before review, and `tests/unit/test_skill_neutrality.py` now enforces it.

## 2026-10-10 — skills — split into one skill per component + coordinator (M2 step 1)
- **Reason:** User: "I think it is better ton have skills for each component seperately on how to login and what to looks and command to search based on time, cluster, topic. for kafaka like wise for others, create sperate skills files"
- **Triggering run transcript:** none (no agent runs yet). This is a design decision from review.
- **Change:**
  - New `incident-app-logs`, `incident-app-config`, `incident-kafka`, `incident-db-logs` (v0). Each has: logging in (user SSO, exit codes 3/4), where the inputs come from, commands to search by time/cluster/topic/ID/thread, output format, what to look for.
  - `incident-logs` reduced to a coordinator (v0.1): hard rules, step → skill table, default time window.
  - New in this version:
    - the cluster dimension (`--context`, `--bootstrap-server`, `--host`);
    - Kafka time search via `kafka-get-offsets`;
    - `cluster`/`namespace` in the app log format;
    - DB/Kafka-specific Forbidden messages.
  - `test_skill_neutrality.py` now covers all five skills and checks that component skills have the required sections.

## 2026-10-10 — skills — required inputs ("no input, no access") + incident format
- **Reason:** User: "The incident will mention the what will be inouts for each siource, i.e. we need kafka server cluster and topic and for each db same as well. Make it cler in the skills what is the inouts required to execute the skills, if the required inout is not present we will not try to access the logs."
- **Triggering run transcript:** none (no agent runs yet). This is a design decision from review.
- **Change:**
  - Coordinator v0.2: hard rule 1 "No input, no access"; a proposed `INCIDENT` message format (seed + `app:` / `app[<name>]:` / `kafka:` / `db:` lines); the step table now lists the required inputs per step.
  - Component skills v0.1: section 2 is now "Required inputs" (input | required? | where it must come from), followed by the rule "If any required input is missing, don't run any command from this skill" → `missing_input` gap.
  - The config is no longer a source of Kafka/DB access inputs. It's only used for direction/group/limits (pending confirmation), and mismatches against the incident get reported.
  - Removed the "assume the seed's cluster" guidance for related apps (R21 withdrawn).
  - The structure test now enforces the Required-inputs section and the rule in every component skill, plus the rule and the format in the coordinator.

## 2026-10-10 — skills — "pending confirmation" markers removed (approved)
- **Reason:** User approved the skills: "nice the skills are fine now. commit and goahead with next steps". The two open points were taken as approved as written: (a) the plain `app:` line = the seed app only, so related apps need `app[<name>]:`; (b) the config may supply topic direction and the consumer group.
- **Triggering run transcript:** none (no agent runs yet).
- **Change:** Removed the "pending user confirmation" markers in `incident-logs`, `incident-app-logs`, `incident-kafka` and `incident-app-config`. No rule changed.

## 2026-10-10 — skills — cross-service correlation by business key (D25)
- **Reason:** User: "So Correleantion ID is only for in app logs search, For different upstreams and different sub services inside in the service it has different correleation id accross distributed systems." … "if the error Log is from Order* file, fetch the order_id from the log and use it to correlate and if The log is from Product* the correlation shoudl be product id. In kafka and db logs the product id is stored in product_id and order_id is stored in order_id."
- **Triggering run transcript:** none (no agent runs yet). This is a correction from the user's review.
- **Change:**
  - Coordinator v0.3: hard rule 10 (`correlation_id` is in-app only), and a new §3 "Which ID correlates across services" with a machine-readable `correlation_keys` JSON table (`Order` → `order_id`, `Product` → `product_id`; more rules to come from the user). The step table now uses the business key for Kafka, related apps and DB.
  - `incident-app-logs` v0.2: business key required for related apps; a separate business-key search; `correlation_id` only for the same app.
  - `incident-kafka` v0.2: message search by the business key in the value; the header `correlation_id` is the producer's own.
  - `incident-db-logs` v0.2: a business-key search.
  - A test checks that the JSON table parses and has both rules.

## 2026-10-10 — incident-logs — OrderService / ProductService domain note
- **Reason:** User: "For All product based inpusts comes from Product Service and Orders come from OrderService and it has logs of the whichbwill have the order_id and the the correlation id in app should/will match it"
- **Triggering run transcript:** none (no agent runs yet).
- **Change:** Coordinator §3 gains "Where the keys come from": the OrderService logs `order_id`, the ProductService logs `product_id`, each with its own correlation ID that's consistent within the service. Search by the business key first, then by the correlation ID found. The key table is unchanged.

## 2026-10-10 — component skills — real neutral samples + exit-5 handling (M2 close-out)
- **Reason:** User: "Real samples in the skills: swap the illustrative examples for real mocklogs output, generated from a neutral fixture so no scenario names appear, and add what to do on exit 5 (not found or unreachable)." / "Okay"
- **Triggering run transcript:** none (no agent runs yet).
- **Change:**
  - Every sample block in the four component skills is now real `mocklogs` output (command, banner, output, exit code), rendered by `python -m mocklogs.skill_samples --write` from a neutral fixture: all names `example-*`, benign lines only (health check, healthy lag, routine broker/DB activity) plus the refusals.
  - Blocks are delimited by `<!-- mocklogs-sample: <key> -->` markers.
  - Each component skill documents exit **5** (not found / unreachable → `not_found`; don't retry, don't try other values). Coordinator rule 8 covers exit codes 4 and 5.
  - New tests: samples must equal the generator's output, every sample is used exactly once, no scenario story phrases appear in any skill, and exit codes 3/4/5 are documented.

## 2026-10-10 — skills — related apps and Kafka client IDs come only from the seed config (D26)
- **Reason:** User: "Dont map like that, just map kafka client details from the config you get from kubectl for the application and then get access to kafak clients. In our application in config we define upstream/downstream consumers and dbs in a config file that is accessible from kubectl config,"
- **Triggering run transcript:** none (no agent runs yet).
- **Change:**
  - Coordinator v0.4: new hard rule 11, "Never infer an app from a name". Step 4 targets are the config's `upstream.apps` / `downstream.apps`; no config → `missing_input`.
  - `incident-app-config` v0.2: documents `kafka.*.client.id`, `upstream/downstream.apps` and `*.kafka.client.ids`.
  - `incident-kafka` v0.3:
    - removed "Its `CLIENT-ID` is the app name";
    - `CLIENT-ID`/`clientId=` are attributed only via the config;
    - the `producer_app` header attributes a single message, and a mismatch with the config is reported;
    - removed the fallback "treat any producer other than the seed app as upstream".
  - `incident-app-logs` v0.3: related apps come from the config.
  - Real samples regenerated (configmap gains the declarations; `CLIENT-ID`s are now `<app>-consumer-1`).

## 2026-10-10 — incident-logs — "where vs. who" stated explicitly (D27)
- **Reason:** The user confirmed "the incident stay the only source of where to look, with the config only saying who is related" ("This is correct").
- **Triggering run transcript:** none.
- **Change:** One bullet added to coordinator §2. No rule changed: the component skills already said the config is never a source of access inputs.

## 2026-10-10 — incident-kafka v0.4 + coordinator v0.5 — collect first; Kafka collection scope (D28)
- **Reason:** User: "The llm assesing what is wrong with the log comes after for now we need to collect logs for all related events and then we can debug. In kafka check incoming, outgoing and any retires logs. that is all. but also for kafka any topic that error, connection timedout related to the topic should be of concern. Edit skills file accordingly."
- **Triggering run transcript:** none.
- **Change:**
  - Coordinator: new rule 0 "Collect first, assess later"; step 3 now lists the four Kafka collections.
  - `incident-kafka`: §3 is now a collection table: incoming (consumed topics), outgoing (produced topics), retries (unfiltered producer/consumer logs), topic errors and connection timeouts (broker + client logs). Plus the message and log commands.
    - The consumer-group lag and all-groups commands, their sample and the `group` input row were removed.
    - §5 became a collection checklist.
    - No `--grep` on client/broker logs, so retries and timeouts without the business key aren't lost.
  - Sample generator: `kafka/lag` removed. A test pins the four collections and the absence of `kafka-consumer-groups`.

## 2026-10-10 — incident-logs v1 — procedure: `investigator plan` drives collection (M5)
- **Reason:** M5 plan ("SKILL.md v1: the traversal section"), with the user's approval to start M5 ("Yes go ahead with m5").
- **Triggering run transcript:** none from an agent yet. The procedure was validated by a scripted loop (scratch walkthrough, 4 rounds) and by `tests/integration/test_planner.py`.
- **Change:** new §6 "Procedure":
  - the incident is saved as `<workdir>/incident.txt`;
  - loop `investigator plan` → run every `argv` exactly, in order → until `"done": true`;
  - exit 3: ask the user, then re-plan (one retry); exits 4/5 become gaps;
  - keep all gaps for the report.
  The time window is now stated as computed by the planner. A test pins the procedure.

## 2026-10-10 — all skills — v2: investigate through a checked runner; allowlists; report contract (M10, D31)
- **Reason:** D31 (the user: "AI should do the investigations but not be a just the narraotr") and the M10 plan, approved with "Approve M9 and go ahead with M10".
- **Triggering run transcript:** none from an agent yet (M11 adds runs). The behaviour is covered by `tests/integration/test_runner.py` and `tests/unit/test_skill_neutrality.py`.
- **Change:**
  - Coordinator v2:
    - rule 0 extended ("once collected, you investigate");
    - rules 5–6 now say every fetch goes through `investigator run --reason`;
    - §6 is the investigation procedure (init → plan suggestions → run → correlate → dig → choose the cause and `score` it → report);
    - new §7 report contract.
  - Component skills (app-logs v0.4, app-config v0.3, kafka v0.5, db-logs v0.3): new §6 machine-readable allowlist, the single source of truth read by the guard.
  - Tests: every documented command is allowlisted (canary: removing `--thread` failed it); `sso login` is never allowlisted.

## 2026-10-11 — new subagent `incident-investigator` v0.1 + allowlist hook (M12, D32)
- **Reason:** D32. The user: "YEah i want this application to run with the my claude account not with api key", then "Pathj 2".
- **Triggering run transcript:** none yet. There are no live runs until the user approves. Behaviour is covered by `tests/integration/test_claude_code.py` (fake `claude`) and `tests/unit/test_allowlist_hook.py`.
- **Change:**
  - `.claude/agents/incident-investigator.md`:
    - tools Bash, Read, Write; `maxTurns: 60`;
    - all five skills preloaded;
    - a `PreToolUse` hook on Bash;
    - the body points to the coordinator §6 procedure, writes the report with Write, then runs `investigator validate`, with at most 3 attempts.
  - `.claude/hooks/allowlist_guard.py`: Bash may run only `investigator {init,plan,run,correlate,check,score,validate,render}` as one plain command. Shell operators, redirections and substitutions are blocked (exit 2), with a reason shown to the model.
  - Skills unchanged.

## 2026-10-11 — subagent `incident-investigator` v0.1 → harness-side guard (M12)
- **Reason:** in the first live run, the frontmatter PreToolUse hook didn't fire (AI_NOTES 2026-10-11, "First live runs").
- **Triggering run transcript:** `runs/20261011T165123162161Z-claude-code-upstream-timeout.jsonl`; the fix is verified in `runs/20261011T165656Z-claude-code-guard-check.jsonl`.
- **Change:**
  - The subagent file is unchanged; its frontmatter hook is kept but is unverified.
  - The harness now passes the same hook through `--settings` by absolute path, plus per-subcommand allow rules, a deny for `investigator agent`, and read denies for `src/`, `tests/`, `docs/` and `runs/`.
