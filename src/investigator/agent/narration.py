"""A compact, deterministic view of the AnalysisBundle for the LLM's context (the full bundle can be large).

Only facts from the bundle; nothing is inferred here. Event IDs are kept, so the LLM can cite them.
"""

from __future__ import annotations

from typing import Any, Dict, List

from investigator.models import AnalysisBundle, Severity

MAX_TIMELINE = 120
MSG_CHARS = 200


def _event_line(e) -> Dict[str, Any]:
    err = (e.attrs.get("error") or {}).get("message")
    return {
        "event_id": e.event_id,
        "ts": e.ts_utc.isoformat() if e.ts_utc else None,
        "source": e.source.value,
        "where": e.app or e.component or e.source.value,
        "severity": e.severity.value,
        "code": e.error_code,
        "msg": (e.message + (f" | error: {err}" if err else ""))[:MSG_CHARS],
        "keys": e.keys or None,
    }


def summarize(bundle: AnalysisBundle) -> Dict[str, Any]:
    by_id = {e.event_id: e for e in bundle.events}
    cited = {eid for f in bundle.findings for eid in f.event_ids}
    timeline: List[Dict[str, Any]] = [_event_line(by_id[t.event_id]) for t in bundle.timeline
                                      if t.event_id in by_id][:MAX_TIMELINE]
    unexplained = [_event_line(e) for e in bundle.events
                   if e.severity in (Severity.ERROR, Severity.SYMPTOM, Severity.ANOMALY) and e.event_id not in cited
                   and (bundle.seed is None or e.event_id != bundle.seed.event_id)]
    return {
        "seed": _event_line(by_id[bundle.seed.event_id]) if bundle.seed and bundle.seed.event_id in by_id else None,
        "seed_correlation_id": bundle.seed.correlation_id if bundle.seed else None,
        "business_key": ({bundle.seed.business_key: bundle.seed.keys.get(bundle.seed.business_key)}
                         if bundle.seed and bundle.seed.business_key else None),
        "confidence_cap": bundle.confidence_cap.value,
        "leads": [{
            "hyp_id": h.hyp_id,
            "cause": _event_line(by_id[h.cause_event_id]) if h.cause_event_id in by_id else h.cause_event_id,
            "effect_event_ids": h.effect_event_ids,
            "ceiling": h.ceiling.value,
            "factors": [{"name": f.name.value, "value": f.value.value, "reason": f.reason} for f in h.factors],
            "summary": h.summary,
        } for h in bundle.hypotheses],
        "findings": [{"finding_id": f.finding_id, "detector": f.detector, "summary": f.summary,
                      "event_ids": f.event_ids} for f in bundle.findings],
        "gaps": [{"target": g.target, "reason": g.reason.value, "detail": g.detail} for g in bundle.coverage_gaps],
        "unexplained_errors_and_symptoms": unexplained,
        "timeline": timeline,
        "timeline_truncated": len(bundle.timeline) > MAX_TIMELINE,
    }
