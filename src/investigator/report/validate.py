"""Validate an AI-written report against the evidence. Errors are machine-readable so the AI can retry.

Rules (each has a code):
  missing_section         a required section is absent or has the wrong type
  unknown_event_id        a cited event_id isn't among the collected events
  root_cause_no_evidence  a root cause without evidence (or without the cause in its evidence list)
  confidence_above_ceiling  the claimed level is above the ceiling `investigator score` gives that cause
  factors_mismatch        the reported factor values differ from the computed ones (the AI can't restate them)
  unknown_root_cause_confident  root_cause "unknown" with any level other than INSUFFICIENT
  insufficient_with_cause a named root cause reported as INSUFFICIENT (contradiction)
  wrong_correlation_id    correlation_id isn't the seed's own
  gap_not_acknowledged    a coverage gap isn't listed in `gaps`
  timeline_out_of_order   timeline entries aren't in event-time order
  bad_value               an enum/field has an invalid value
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from investigator.models import AnalysisBundle, Confidence, Event, Hypothesis
from investigator.report.model import ALT_STATUS, REQUIRED_SECTIONS, ROOT_CAUSE_SOURCES, cited_event_ids

LEVELS = [c.value for c in Confidence]
_TYPES = {"summary": str, "timeline": list, "evidence": list, "downstream_symptoms": list,
          "alternative_hypotheses": list, "confidence": dict, "gaps": list, "ai_interpretations": list,
          "next_steps": list}


@dataclass
class ValidationError:
    code: str
    path: str
    detail: str


def validate(report: Any, bundle: AnalysisBundle, events: Dict[str, Event],
             score: Callable[[str], Hypothesis]) -> List[ValidationError]:
    """`events`: every collected event by ID (the AI may cite beyond the bundle subset).
    `score(event_id)`: the factors + ceiling for a cause (investigator score)."""
    errs: List[ValidationError] = []

    def err(code: str, path: str, detail: str) -> None:
        errs.append(ValidationError(code, path, detail))

    if not isinstance(report, dict):
        return [ValidationError("missing_section", "$", "the report must be a JSON object")]
    for section in REQUIRED_SECTIONS:
        if section not in report:
            err("missing_section", section, f"required section '{section}' is missing")
        elif section in _TYPES and not isinstance(report[section], _TYPES[section]):
            err("missing_section", section, f"'{section}' must be a {_TYPES[section].__name__}")
    if errs:
        return errs  # structure first; content checks assume it

    for eid in cited_event_ids(report):
        if eid not in events:
            err("unknown_event_id", "$", f"cited event_id {eid!r} isn't among the collected events")

    seed = bundle.seed
    if report["correlation_id"] != (seed.correlation_id if seed else None):
        err("wrong_correlation_id", "correlation_id",
            f"must be the seed's own correlation ID ({seed.correlation_id if seed else None!r})")

    level = report["confidence"].get("level")
    if level not in LEVELS:
        err("bad_value", "confidence.level", f"must be one of {LEVELS}")
        return errs
    claimed = Confidence(level)
    rc = report["root_cause"]
    if rc == "unknown":
        if claimed is not Confidence.INSUFFICIENT:
            err("unknown_root_cause_confident", "confidence.level", "an unknown root cause must be INSUFFICIENT")
    elif not isinstance(rc, dict):
        err("missing_section", "root_cause", "root_cause must be an object or the string \"unknown\"")
    else:
        cause = rc.get("cause_event_id")
        evidence = list(rc.get("evidence_event_ids") or [])
        if rc.get("source") not in ROOT_CAUSE_SOURCES:
            err("bad_value", "root_cause.source", f"must be one of {list(ROOT_CAUSE_SOURCES)}")
        if not rc.get("statement"):
            err("missing_section", "root_cause.statement", "the root cause needs a statement")
        if not evidence or not report["evidence"] or cause not in evidence:
            err("root_cause_no_evidence", "root_cause",
                "a root cause needs evidence_event_ids that include the cause, and a non-empty evidence list")
        if claimed is Confidence.INSUFFICIENT:
            err("insufficient_with_cause", "confidence.level",
                "a named root cause can't be INSUFFICIENT; use root_cause \"unknown\"")
        if cause in events:
            scored = score(cause)
            if not claimed.at_most(scored.ceiling):
                err("confidence_above_ceiling", "confidence.level",
                    f"claimed {claimed.value} but the ceiling for this cause is {scored.ceiling.value}")
            computed = {f.name.value: f.value.value for f in scored.factors}
            reported = {f.get("name"): f.get("value") for f in report["confidence"].get("factors") or []
                        if isinstance(f, dict)}
            if reported != computed:
                err("factors_mismatch", "confidence.factors",
                    f"factors must match the computed values {computed} (reasons may be reworded)")

    acknowledged = {g.get("target") for g in report["gaps"] if isinstance(g, dict)}
    for gap in bundle.coverage_gaps:
        if gap.target not in acknowledged:
            err("gap_not_acknowledged", "gaps", f"coverage gap on {gap.target!r} ({gap.reason.value}) isn't listed")

    times = [events[t["event_id"]].ts_utc for t in report["timeline"]
             if isinstance(t, dict) and t.get("event_id") in events and events[t["event_id"]].ts_utc]
    if any(b < a for a, b in zip(times, times[1:])):
        err("timeline_out_of_order", "timeline", "timeline entries must be in event-time order")

    for i, alt in enumerate(report["alternative_hypotheses"]):
        if not isinstance(alt, dict) or alt.get("status") not in ALT_STATUS:
            err("bad_value", f"alternative_hypotheses[{i}].status", f"must be one of {list(ALT_STATUS)}")
    if not report["next_steps"]:
        err("missing_section", "next_steps", "at least one next step is required")
    return errs
