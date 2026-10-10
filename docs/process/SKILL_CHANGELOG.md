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
