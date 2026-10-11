# runs/

Full transcripts of every agent run, named `<timestamp>-<scenario>.jsonl` (UTC timestamp, e.g. `20261010T171717Z-upstream-timeout.jsonl`). These are kept permanently. Old runs are never deleted.

**Conventions:**
- Agent runs of the product (the CLI `investigator agent`, real or fake provider) are kept here. Test runs use temporary folders and aren't kept.
- **The workdir path is visible to the model.** It must be neutral (e.g. `case-3`), never one that hints at the scenario.

**Known flawed runs (kept, per the never-delete rule):** the first five transcripts from 2026-10-11 (`20261011T062848…-upstream-timeout` and the four `20261011T06313…-fake-*`) used workdir paths containing the scenario name, which leaked it into the model-visible content. The scripted fake never reads paths, so those runs' results are unaffected, but they aren't valid examples. The clean reruns are the `20261011T06320…-fake-*` files.

**Claude Code runs (M12):**
- `20261011T165123162161Z-claude-code-upstream-timeout.jsonl`: the first live run on the user's login. It ran **before** the guard fixes: the agent hook didn't fire, and reads of `src/` weren't denied. The agent ran only `investigator` commands and read only its own tool output and the coordinator skill, so the result stands, but it is not an example of the final guardrails.
- `20261011T165656Z-claude-code-guard-check.jsonl`: a guardrail check, not an investigation. It tried forbidden calls on purpose; all were blocked.
- `20261011T170019…-claude-code-{db-config,consumer-processing,ambiguous}.jsonl`: live runs with the final limits. Results: MEDIUM / HIGH / INSUFFICIENT, all valid (see AI_NOTES).
