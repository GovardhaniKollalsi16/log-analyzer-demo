"""Application logs (PROPOSAL §2.1). Ordered: the first match wins; no match = CONTEXT."""

from __future__ import annotations

from investigator.classify.rules import ERROR_LEVELS, Rule, rx
from investigator.models import Level, Severity

E, S = Severity.ERROR, Severity.SYMPTOM

RULES = [
    # --- ERROR: the app failed to do its job --------------------------------------
    # publish_failed comes first: an app-level "failed to publish" whose cause is an expired
    # record is a publish failure; the client's own "Expiring N record(s)" line is retries_exhausted.
    Rule("app.publish_failed", E, "Failed to publish/send/produce after the final attempt",
         levels=ERROR_LEVELS, pattern=rx(r"fail(ed|ure)? to (publish|send|produce)")),
    Rule("app.retries_exhausted", E, "Retries exhausted / gave up / records expired after retrying",
         pattern=rx(r"retries exhausted|giving up|gave up|expiring \d+ record")),
    Rule("app.event_wait_timeout", E, "Timed out waiting for an expected event/message/response",
         levels=ERROR_LEVELS, pattern=rx(r"timed out waiting for")),
    Rule("app.db_call_failed", E, "A database call failed",
         levels=ERROR_LEVELS, pattern=rx(r"\b(sql|jdbc|database|db call|statement|connection pool|DataAccess)")),
    Rule("app.outbound_timeout", E, "An outbound call timed out",
         levels=ERROR_LEVELS, pattern=rx(r"time(d)? ?out")),
    Rule("app.exception", E, "Any other ERROR/FATAL record",
         levels=ERROR_LEVELS),
    # --- SYMPTOM: degraded, not failed -----------------------------------------------
    Rule("app.retry_attempt", S, "One retry attempt (more attempts left)",
         pattern=rx(r"\bretrying\b|\bretry (attempt )?\d+|attempt \d+ ?/ ?\d+|attempts left")),
    Rule("app.circuit_open", S, "Circuit breaker opened",
         pattern=rx(r"circuit( breaker)? (is )?open")),
    Rule("app.pool_saturated", S, "Thread pool / queue saturated or exhausted",
         pattern=rx(r"(pool|queue) (is )?(exhausted|saturated|full)|rejected execution")),
    Rule("app.slow_call", S, "Operation slower than its stated threshold",
         pattern=rx(r"took \d+(\.\d+)? ?ms \(threshold \d+")),
    Rule("app.warning", S, "Any other WARN record",
         levels=(Level.WARN,)),
]
