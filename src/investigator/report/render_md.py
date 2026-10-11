"""Report JSON -> Markdown (D4: the JSON is the validated source of truth; this is a view of it)."""

from __future__ import annotations

from typing import Any, Dict

from investigator.models import Event


def _ev(eid: str, events: Dict[str, Event]) -> str:
    e = events.get(eid)
    if e is None:
        return f"`{eid}`"
    ts = e.ts_utc.strftime("%H:%M:%S.%f")[:12] if e.ts_utc else "config"
    where = e.app or e.component or e.source.value
    return f"`{eid}` ({ts}, {where})"


def render(report: Dict[str, Any], events: Dict[str, Event]) -> str:
    out = ["# Incident report", "", "> MOCK DATA — synthetic investigation, not a real system.", ""]
    conf = report["confidence"]
    out += [f"**Confidence:** {conf['level']}", "", "## Summary", "", report["summary"], ""]
    if report.get("correlation_id"):
        out += [f"**Seed correlation ID:** `{report['correlation_id']}`", ""]
    rc = report["root_cause"]
    out += ["## Root cause", ""]
    if rc == "unknown":
        out += ["**Unknown:** the evidence doesn't support a conclusion.", ""]
    else:
        out += [f"{rc['statement']}", "", f"- Cause: {_ev(rc['cause_event_id'], events)} "
                f"(proposed by: {'detector' if rc.get('source') == 'detector' else 'AI investigation'})", ""]
    if report["evidence"]:
        out += ["## Evidence", ""] + [f"- {_ev(e['event_id'], events)}: {e['why']}" for e in report["evidence"]] + [""]
    if report["timeline"]:
        out += ["## Timeline", ""] + [f"- {_ev(t['event_id'], events)}: {t['note']}" for t in report["timeline"]] + [""]
    if report["downstream_symptoms"]:
        out += ["## Downstream symptoms", ""]
        out += [f"- {s['statement']} ({', '.join(_ev(i, events) for i in s['event_ids'])})"
                for s in report["downstream_symptoms"]] + [""]
    if report["alternative_hypotheses"]:
        out += ["## Alternative hypotheses", ""]
        out += [f"- **{a['status']}**: {a['statement']}. {a['why']}" for a in report["alternative_hypotheses"]] + [""]
    if conf.get("factors"):
        out += ["## Confidence factors", "", "| Factor | Value | Reason |", "|---|---|---|"]
        out += [f"| {f['name']} | {f['value']} | {f.get('reason', '')} |" for f in conf["factors"]] + [""]
    if report["gaps"]:
        out += ["## Gaps in what could be collected", ""]
        out += [f"- `{g['target']}` ({g['reason']}): {g.get('impact', '')}" for g in report["gaps"]] + [""]
    if report["ai_interpretations"]:
        out += ["## AI interpretations (not used to raise confidence)", ""]
        out += [f"- {_ev(i['event_id'], events)}: {i['interpretation']}" for i in report["ai_interpretations"]] + [""]
    out += ["## Next steps", ""] + [f"{n}. {s}" for n, s in enumerate(report["next_steps"], start=1)]
    return "\n".join(out) + "\n"
