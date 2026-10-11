"""The incident report the AI submits (JSON), and the deterministic fail-closed fallback.

Sections (all required; lists may be empty where noted):
  summary                str
  correlation_id         str | null       the seed's own correlation ID (null if it has none)
  timeline               [{event_id, note}]                  ordered by event time
  root_cause             {statement, cause_event_id, evidence_event_ids, source: "detector"|"ai"} | "unknown"
  evidence               [{event_id, why}]                   non-empty unless root_cause is "unknown"
  downstream_symptoms    [{statement, event_ids}]            may be empty
  alternative_hypotheses [{statement, event_ids, status: "rejected"|"open", why}]   may be empty
  confidence             {level: HIGH|MEDIUM|LOW|INSUFFICIENT, factors: [{name, value, reason}]}
  gaps                   [{target, reason, impact}]          every coverage gap must be acknowledged
  ai_interpretations     [{event_id, interpretation}]        labeled AI reading of unclassified errors
  next_steps             [str]                               non-empty
"""

from __future__ import annotations

from typing import Any, Dict, List

from investigator.models import AnalysisBundle, Confidence

REQUIRED_SECTIONS = ["summary", "correlation_id", "timeline", "root_cause", "evidence", "downstream_symptoms",
                     "alternative_hypotheses", "confidence", "gaps", "ai_interpretations", "next_steps"]
ROOT_CAUSE_SOURCES = ("detector", "ai")
ALT_STATUS = ("rejected", "open")


def fallback_report(bundle: AnalysisBundle, why: str) -> Dict[str, Any]:
    """Fail closed (D12): when the AI's report can't be validated, report INSUFFICIENT with the facts."""
    seed_id = bundle.seed.event_id if bundle.seed else None
    gaps = [{"target": g.target, "reason": g.reason.value, "impact": "evidence from this source is missing"}
            for g in bundle.coverage_gaps]
    leads = [{"statement": h.summary, "event_ids": [h.cause_event_id], "status": "open",
              "why": f"detector lead (ceiling {h.ceiling.value}); not confirmed because: {why}"}
             for h in bundle.hypotheses]
    next_steps = ["Review the detector leads and the collected events manually."]
    next_steps += [f"Obtain {g['target']} ({g['reason']}) and re-run the investigation." for g in gaps]
    return {
        "summary": f"Insufficient evidence for a validated conclusion ({why}).",
        "correlation_id": bundle.seed.correlation_id if bundle.seed else None,
        "timeline": [{"event_id": seed_id, "note": "the incident's seed error"}] if seed_id else [],
        "root_cause": "unknown",
        "evidence": [],
        "downstream_symptoms": [],
        "alternative_hypotheses": leads,
        "confidence": {"level": Confidence.INSUFFICIENT.value, "factors": []},
        "gaps": gaps,
        "ai_interpretations": [],
        "next_steps": next_steps,
    }


def cited_event_ids(report: Dict[str, Any]) -> List[str]:
    """Every event ID the report cites, wherever it appears."""
    ids: List[str] = []
    ids += [t.get("event_id") for t in report.get("timeline") or [] if isinstance(t, dict)]
    rc = report.get("root_cause")
    if isinstance(rc, dict):
        ids.append(rc.get("cause_event_id"))
        ids += list(rc.get("evidence_event_ids") or [])
    ids += [e.get("event_id") for e in report.get("evidence") or [] if isinstance(e, dict)]
    for key in ("downstream_symptoms", "alternative_hypotheses"):
        for item in report.get(key) or []:
            if isinstance(item, dict):
                ids += list(item.get("event_ids") or [])
    ids += [i.get("event_id") for i in report.get("ai_interpretations") or [] if isinstance(i, dict)]
    return [i for i in ids if i is not None]
