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
