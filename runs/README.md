# runs/

Full transcripts of every agent run, named `<timestamp>-<scenario>.jsonl` (UTC timestamp, e.g. `20261010T171717Z-upstream-timeout.jsonl`). These are kept permanently. Old runs are never deleted.

**Conventions:**
- Agent runs of the product (the CLI `investigator agent`, real or fake provider) are kept here. Test runs use temporary folders and aren't kept.
- **The workdir path is visible to the model.** It must be neutral (e.g. `case-3`), never one that hints at the scenario.

**Known flawed runs (kept, per the never-delete rule):** the first five transcripts from 2026-10-11 (`20261011T062848…-upstream-timeout` and the four `20261011T06313…-fake-*`) used workdir paths containing the scenario name, which leaked it into the model-visible content. The scripted fake never reads paths, so those runs' results are unaffected, but they aren't valid examples. The clean reruns are the `20261011T06320…-fake-*` files.

