# M7 rules: detectors, hypotheses, confidence ceiling (PROPOSED, awaiting user approval)

Nothing in this file is coded yet. Edit it directly or comment in chat. Once approved, it becomes the spec for M7's code and tests.

**Pipeline:** collected records → classify (M4) → link + group + timeline (M6) → **detectors** (find patterns) → **hypotheses** (candidate causes) → **confidence factors** → **confidence ceiling** → bundle (what the LLM reads). The LLM then writes the report and may claim **at most** the ceiling (validator, M9).

---

## 1. Detectors (proposed)

Each detector looks at the seed's group (and the incident window) and emits **Findings**. A finding always cites the event IDs it's based on.

| # | Detector | Fires when | Cites | Changes vs. the original M7 list |
|---|---|---|---|---|
| D-1 | **retry_exhaustion** | ≥ 2 retry SYMPTOMs (`*.retry*`) followed by a give-up/expiry ERROR for the same Kafka client or resource | the retries + the final error | was "retry amplification" |
| D-2 | **delivery_failure_chain** | a broker ERROR/SYMPTOM on topic-partition X **and** a producer/app ERROR naming X, linked to the seed group | broker + producer + app events | same |
| D-3 | **missing_message** | the seed's business key was searched on an incident topic and **no message** was found, while an app logged a publish failure or a wait timeout for that key | the publish-failure / timeout events; the empty searches are listed as `absence` (commands, not event IDs) | new, from "a missing message is a finding" (D28) |
| D-4 | **poison_message** | ≥ 3 consumer processing failures or redeliveries on the same topic-partition-offset | those consumer events | same (scenario 3, D29) |
| D-5 | **db_error_burst** | ≥ 3 DB ERRORs from the same app/DB inside the window | those DB events | same |
| D-6 | **config_vs_observed** | a config ANOMALY (M4) **plus** observed errors it explains: pool < threads with `db.too_many_connections` / `app.pool_saturated`; a timeout key vs. `db.statement_timeout` / `app.outbound_timeout` | config event(s) + observed events | the cross-source config checks moved from M4 |
| D-7 | **first_error_per_app** | always: the earliest ERROR per app in the seed group | one event per app | same |
| — | ~~lag growth / stuck partition~~ | — | — | **dropped: lag deferred (D29)** |
| — | *transient exception* (exception then success, same correlation ID → SYMPTOM) | — | — | **still only proposed: include it?** |

---

## 2. Hypotheses (candidate causes)

A **hypothesis** = one candidate cause plus the effects it explains, built only from findings:
- **Cause candidates:** the earliest ERROR/SYMPTOM/ANOMALY record of each finding chain that is **not** the seed itself and **precedes** the seed.
- **Effects:** the seed, plus other findings linked to the cause.
- A chain such as broker ISR shrink → producer retries → expiry → publish failure → seed is **one** hypothesis (the earliest link is the cause), not five.
- Hypotheses are **unranked facts**. The code never picks "the" root cause; the LLM chooses, or says INSUFFICIENT.

---

## 3. Confidence factors (each: STRONG / PARTIAL / WEAK / ABSENT)

Computed per hypothesis. The bundle reports each factor **with a reason**.

| Factor | STRONG | PARTIAL | WEAK | ABSENT |
|---|---|---|---|---|
| **id_linkage**: how the cause connects to the seed | a path made only of same-app correlation ID, the seed's business key, same-occurrence, or a topic-partition **named by an ERROR record** | the path needs a thread-segment hop, or a topic-partition link between non-error records | only time proximity, no link path | the cause isn't in the seed's group |
| **traversal_coverage**: how much of the planned collection succeeded | no relevant gaps | gaps only on **downstream** apps, or on a DB the seed config doesn't declare | a gap on the seed config, on Kafka, or on an **upstream** app | the seed app's own logs are missing |
| **temporal_precedence**: does the cause come first? | the cause precedes every effect and the seed | — | the cause precedes the seed but not all effects | the cause comes after the seed |
| **competing_hypotheses**: are there rivals? | this is the only hypothesis | rivals exist but have weaker `id_linkage` | ≥ 1 rival with equally strong `id_linkage` | — |

"Relevant gap" = `access_denied`, `auth_required`, `not_found`, or `missing_input` on a step the topology says matters (seed config, an incident Kafka topic, a declared related app, or a DB the seed config declares). A missing `db:` line when the seed config declares no DB isn't relevant.

---

## 4. The confidence ceiling (the maximum the report may claim)

Start at **HIGH** and lower it; the lowest rule that applies wins:

| Condition | Ceiling at most |
|---|---|
| No hypothesis at all (no linked earlier error/symptom/anomaly) | **INSUFFICIENT** |
| `id_linkage` ABSENT, or `temporal_precedence` ABSENT | **INSUFFICIENT** |
| `id_linkage` WEAK, or `traversal_coverage` WEAK, or `temporal_precedence` WEAK, or `competing_hypotheses` WEAK | **LOW** |
| `id_linkage` PARTIAL, or `traversal_coverage` PARTIAL, or `competing_hypotheses` PARTIAL | **MEDIUM** |
| Seed app logs missing (`traversal_coverage` ABSENT) | **INSUFFICIENT** |
| All four factors STRONG | **HIGH** |

The bundle's ceiling is the **highest** ceiling among the hypotheses. Each hypothesis also carries its own ceiling, so the LLM can't claim HIGH for a weaker one.

### What these rules would give (by hand, before any code)

| Scenario | Expected ceiling | Why |
|---|---|---|
| 1 upstream-timeout (as collected today) | **HIGH** | one hypothesis (the ISR shrink chain); linked by business key + topic-partition named in ERRORs; no relevant gaps; the cause precedes everything |
| 1 with the seed config denied | **LOW** | `traversal_coverage` WEAK (seed config gap → related apps unknown) |
| 1 with no `app[product-service]:` line | **LOW** | upstream app gap → coverage WEAK; the producer errors are still visible in `kafka logs`, but `id_linkage` to the seed is via resource only |
| 4 ambiguous (M8) | **INSUFFICIENT** | no ID path from the seed to any earlier error |

---

## 5. Questions for the user

1. Is the **detector list** right (dropping lag, adding `missing_message`)?
2. Should the **transient exception** rule be included (exception followed by a later success for the same correlation ID → SYMPTOM)?
3. Are the **factor definitions** and **ceiling rules** right? In particular: should a topic-partition link named by an ERROR record count as **STRONG** linkage, as proposed? It's what makes scenario 1 HIGH.
4. Are the **thresholds** OK: ≥ 2 retries (D-1), ≥ 3 failures (D-4), ≥ 3 DB errors (D-5)?
