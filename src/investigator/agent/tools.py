"""The agent's tools. Each one calls the same guarded code as the CLI; none can bypass a guardrail."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from investigator.agent.narration import summarize
from investigator.agent.provider import ToolSpec
from investigator.correlation_keys import load_rules
from investigator.models import to_jsonable
from investigator.pipeline import analyse_workdir, prepare, score_in_workdir, validate_report_in_workdir
from investigator.planner import plan
from investigator.adapters import FileSource
from investigator.parsing import parse_all
from investigator.runner import run_checked

MAX_OUTPUT = 6000  # characters of command output returned to the model (the full output is saved anyway)

SPECS: List[ToolSpec] = [
    ToolSpec("plan", "Suggested next fetches (argv + reason) and gaps. Suggestions, not orders.",
             {"type": "object", "properties": {}}),
    ToolSpec("run", "Run ONE fetch command through the guard. argv must start with 'mocklogs' and include "
                    "'--save-dir <workdir>'. A denial returns reason codes; nothing runs.",
             {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}},
                                               "reason": {"type": "string"}}, "required": ["argv", "reason"]}),
    ToolSpec("correlate", "Analyse everything collected so far: timeline, findings, detector leads with factors "
                          "and ceilings, gaps, unexplained errors.", {"type": "object", "properties": {}}),
    ToolSpec("score", "Factors and confidence ceiling for a cause YOU propose (any collected event_id).",
             {"type": "object", "properties": {"cause_event_id": {"type": "string"}},
              "required": ["cause_event_id"]}),
    ToolSpec("submit_report", "Submit the final report (JSON object per the report contract). Returns "
                              "validation errors to fix, or accepts it.",
             {"type": "object", "properties": {"report": {"type": "object"}}, "required": ["report"]}),
]


class Tools:
    def __init__(self, workdir: Path, rules_path: Path):
        self.workdir, self.rules_path = workdir, rules_path
        self.rules = load_rules(rules_path)

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handler: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "plan": self._plan, "run": self._run, "correlate": self._correlate, "score": self._score,
        }
        if name not in handler:
            return {"error": f"unknown tool {name!r}"}
        try:
            return handler[name](args)
        except Exception as e:  # a tool failure is reported to the model, never crashes the loop
            return {"error": f"{type(e).__name__}: {e}"}

    def _plan(self, args) -> Dict[str, Any]:
        p = prepare(self.workdir, self.rules)
        source = FileSource(self.workdir)
        fp = plan(p.incident, parse_all(source), list(source.outputs()), str(self.workdir))
        return {"done": fp.done, "steps": [{"argv": s.argv, "reason": s.reason} for s in fp.steps],
                "gaps": [{"target": g.target, "reason": g.reason.value, "detail": g.detail} for g in fp.gaps]}

    def _run(self, args) -> Dict[str, Any]:
        argv, reason = list(args.get("argv") or []), str(args.get("reason") or "")
        if not reason:
            return {"allowed": False, "reasons": [{"code": "reason_missing", "detail": "say why you need this"}]}
        r = run_checked(self.workdir, self.rules_path, argv, reason)
        if not r.allowed:
            return {"allowed": False, "reasons": r.denials}
        return {"allowed": True, "exit_code": r.exit_code, "stdout": r.stdout[:MAX_OUTPUT],
                "stdout_truncated": len(r.stdout) > MAX_OUTPUT, "stderr": r.stderr[:1000]}

    def _correlate(self, args) -> Dict[str, Any]:
        return summarize(analyse_workdir(self.workdir, self.rules))

    def _score(self, args) -> Dict[str, Any]:
        h = score_in_workdir(self.workdir, self.rules, str(args.get("cause_event_id")))
        return {"cause_event_id": h.cause_event_id, "ceiling": h.ceiling.value,
                "factors": [{"name": f.name.value, "value": f.value.value, "reason": f.reason} for f in h.factors]}

    def validate(self, report: Any):
        return validate_report_in_workdir(self.workdir, self.rules, report)


def as_json(result: Dict[str, Any]) -> str:
    return json.dumps(to_jsonable(result))
