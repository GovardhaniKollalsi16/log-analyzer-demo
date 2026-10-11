"""Database logs (PROPOSAL §2.4). Ordered: the first match wins; no match = CONTEXT."""

from __future__ import annotations

import re

from investigator.classify.rules import ERROR_LEVELS, Rule, Thresholds, rx
from investigator.models import Event, Severity

E, S = Severity.ERROR, Severity.SYMPTOM
_DURATION = re.compile(r"duration: (\d+(?:\.\d+)?) ms")


def _slow(t: Thresholds):
    def check(ev: Event) -> bool:
        m = _DURATION.search(ev.message)
        return bool(m) and float(m.group(1)) > t.slow_query_ms
    return check


def rules(t: Thresholds):
    return [
        # --- ERROR (DB severity ERROR/FATAL/PANIC) -------------------------------------
        Rule("db.connection_refused", E, "Connection refused / could not connect",
             pattern=rx(r"connection refused|could not connect")),
        Rule("db.too_many_connections", E, "Too many connections / connection slots exhausted",
             pattern=rx(r"too many (connections|clients)|remaining connection slots are reserved")),
        Rule("db.auth_failed", E, "Authentication failed",
             pattern=rx(r"authentication failed")),
        Rule("db.deadlock", E, "Deadlock detected",
             pattern=rx(r"deadlock detected")),
        Rule("db.statement_timeout", E, "Statement cancelled by a timeout",
             pattern=rx(r"canceling statement due to (statement|lock) timeout")),
        Rule("db.transaction_aborted", E, "Transaction aborted",
             pattern=rx(r"current transaction is aborted")),
        Rule("db.error", E, "Any other ERROR/FATAL/PANIC",
             levels=ERROR_LEVELS),
        # --- SYMPTOM -------------------------------------------------------------
        Rule("db.slow_query", S, f"Statement slower than slow_query_ms ({t.slow_query_ms:g} ms)",
             when=_slow(t)),
        Rule("db.lock_wait", S, "Waiting on a lock",
             pattern=rx(r"still waiting for \S*lock|lock wait")),
        Rule("db.connections_high", S, "Connection count near the limit",
             pattern=rx(r"connections? (count )?(near|approaching) (the )?limit")),
    ]
