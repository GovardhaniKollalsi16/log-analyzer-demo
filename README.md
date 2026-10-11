# Incident investigator (demo)

> **All data is synthetic (MOCK).** No real company, service, schema, customer or person appears anywhere. Every mock command prints a MOCK banner.

An AI agent that investigates a production incident across a distributed system. You give it one error line plus where to look (an *incident*). It:

- collects logs from the app, its configuration, Kafka and the database;
- correlates them into one timeline;
- decides the root cause itself, or says "unknown";
- writes a report in which every claim cites an event ID that the code then checks.

The AI does the investigating. Deterministic code handles the parts that must not be guessed: parsing, linking events, ordering, scoring how much confidence the evidence allows, checking every command before it runs, and validating the report.

It runs as a **Claude Code subagent on your own Claude login** (no API key), started from the command line.

## Quick start

Requires Python 3.9+, and Claude Code installed and logged in (`claude`, then `/login`).

```bash
python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[test]"
```

Pick a mock scenario, log in to the mock systems, and create its incident:

```bash
export MOCKLOGS_SCENARIO=upstream-timeout   # or db-config, consumer-processing, ambiguous
```

```bash
.venv/bin/mocklogs sso login
```

```bash
.venv/bin/mocklogs scenario incident > incident.txt
```

Run the investigation (this uses your Claude account's usage, roughly $0.40–$1.10 per incident in our runs):

```bash
.venv/bin/investigator agent --provider claude-code --workdir ./case-1 --incident-file incident.txt
```

The output goes to `case-1/report.md` (readable) and `case-1/report.json`, with the full transcript in `runs/`. Use a neutral workdir name: the AI sees it.

Run the tests (no Claude usage; a fake `claude` stands in):

```bash
.venv/bin/pytest -q
```

## Example

**Input** (`incident.txt`):
```
seed: {"app":"order-service","order_id":"o-1008","msg":"Timed out waiting for pricing event",
       "error":{"type":"orders.PricingTimeoutException","message":"no pricing event within 30000 ms"}, ...}
app[product-service]: cluster=cluster-a namespace=apps
kafka:  bootstrap=kafka-a:9092 topics=pricing.events,orders.events group=order-service-pricing
```

**Output** (`report.md`, shortened): **Confidence: HIGH.**
- **Root cause:** partition `pricing.events-2` lost 2 of its 3 in-sync replicas. product-service's `acks=all` sends timed out, and after 3 retries the record for o-1008 expired, so order-service's 30-second wait ran out.
- **Evidence:** 9 cited events.
- **Rejected alternatives:** 2.
- **Gap:** one (no DB inputs).
- **Next steps:** included.

## Documentation

- **[How it works](docs/HOW_IT_WORKS.md):** the flow, components, guardrails, confidence and report checks.
- [Design proposal and decisions](docs/design/PROPOSAL.md) · [Milestones](docs/design/MILESTONES.md) · [Rules](docs/design/M7_RULES.md)
- Process records: [prompt log](docs/process/PROMPT_LOG.md) · [AI notes](docs/process/AI_NOTES.md) · [skill changelog](docs/process/SKILL_CHANGELOG.md) · [run transcripts](runs/README.md)
