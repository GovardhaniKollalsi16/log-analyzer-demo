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
