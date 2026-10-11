"""The agent loop (the Python path; the Claude Code subagent path is M13).

  incident file -> `init` (the runtime saves it verbatim, R17) -> the model gets the skills as its system
  prompt and the incident as its first message (D19) -> tool calls until it submits a valid report,
  with at most 3 report attempts (D12) and a turn budget -> otherwise the INSUFFICIENT fallback.
Every message, tool call and result goes to runs/<timestamp>-<label>.jsonl (append-only, never deleted).
The model sees the workdir path (first message, every --save-dir), so choose a neutral workdir name:
never one that hints at the incident or a test scenario (R20). The label only names the transcript file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from investigator.agent.provider import LLMProvider
from investigator.agent.tools import SPECS, Tools, as_json
from investigator.models import to_jsonable
from investigator.parsing.incident import parse_incident
from investigator.pipeline import INCIDENT_FILE, analyse_workdir
from investigator.report.model import fallback_report
from investigator.report.render_md import render

MAX_TURNS = 40
MAX_REPORT_ATTEMPTS = 3  # D12


@dataclass
class AgentResult:
    report: Dict[str, Any]
    valid: bool
    fell_back: bool
    fallback_reason: Optional[str]
    report_attempts: int
    turns: int
    transcript: Path


class Transcript:
    def __init__(self, runs_dir: Path, label: str):
        runs_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = runs_dir / f"{stamp}-{label}.jsonl"
        if self.path.exists():  # never overwrite a previous run
            raise FileExistsError(self.path)

    def write(self, kind: str, **data: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "type": kind, **to_jsonable(data)}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def system_prompt(skills_dir: Path) -> str:
    parts = ["You are an incident investigator. Follow these skills exactly. The workdir for this investigation "
             "is given in the first user message."]
    for name in ("incident-logs", "incident-app-logs", "incident-app-config", "incident-kafka", "incident-db-logs"):
        parts.append((skills_dir / name / "SKILL.md").read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def run_agent(provider: LLMProvider, incident_file: Union[str, Path], workdir: Union[str, Path],
              rules_path: Union[str, Path], runs_dir: Union[str, Path], label: str,
              max_turns: int = MAX_TURNS) -> AgentResult:
    workdir, rules_path = Path(workdir), Path(rules_path)
    tools = Tools(workdir, rules_path)
    incident_text = Path(incident_file).read_text(encoding="utf-8")
    parse_incident(incident_text, tools.rules)  # validate before starting
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / INCIDENT_FILE).write_text(incident_text, encoding="utf-8")  # verbatim (R17)

    transcript = Transcript(Path(runs_dir), label)
    system = system_prompt(rules_path.resolve().parent.parent)
    first = f"workdir: {workdir}\n\n{incident_text}"
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": first}]
    transcript.write("start", label=label, workdir=str(workdir), incident=incident_text,
                     system_prompt_chars=len(system), tools=[s.name for s in SPECS])
    transcript.write("user", content=first)

    attempts, turns = 0, 0
    final: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    while turns < max_turns and final is None:
        turns += 1
        turn = provider.respond(messages, SPECS)
        messages.append({"role": "assistant", "content": turn.text,
                         "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in turn.tool_calls]})
        transcript.write("assistant", text=turn.text, tool_calls=[{"id": c.id, "name": c.name, "args": c.args}
                                                                   for c in turn.tool_calls])
        if not turn.tool_calls:
            reason = "the model stopped without submitting a report"
            break
        for call in turn.tool_calls:
            if call.name == "submit_report":
                attempts += 1
                check = tools.validate(call.args.get("report"))
                result = {"accepted": not check.errors, "attempt": attempts, "max_attempts": MAX_REPORT_ATTEMPTS,
                          "errors": to_jsonable(check.errors)}
                if not check.errors:
                    final = call.args["report"]
                elif attempts >= MAX_REPORT_ATTEMPTS:
                    reason = f"the report failed validation {attempts} times"
            else:
                result = tools.call(call.name, call.args)
            messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": as_json(result)})
            transcript.write("tool_result", tool_call_id=call.id, name=call.name, result=result)
            if final is not None or reason is not None:
                break
        if reason is not None:
            break
    if final is None and reason is None:
        reason = f"turn budget ({max_turns}) exhausted"

    fell_back = final is None
    if fell_back:
        final = fallback_report(analyse_workdir(workdir, tools.rules), reason or "no valid report")
    check = tools.validate(final)
    (workdir / "report.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    if not check.errors:
        (workdir / "report.md").write_text(render(final, check.events), encoding="utf-8")
    transcript.write("final", valid=not check.errors, fell_back=fell_back, fallback_reason=reason,
                     report_attempts=attempts, turns=turns, report=final, errors=to_jsonable(check.errors))
    return AgentResult(report=final, valid=not check.errors, fell_back=fell_back, fallback_reason=reason,
                       report_attempts=attempts, turns=turns, transcript=transcript.path)
