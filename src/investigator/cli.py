"""`investigator`: the deterministic side of the investigation (no LLM).

  investigator plan --workdir <dir> [--rules <coordinator SKILL.md>]
      Reads <dir>/incident.txt and everything saved in <dir>/raw/, prints the next
      fetches as JSON: {"steps": [...argv...], "gaps": [...], "done": bool, ...}.
  investigator correlate --workdir <dir> [--rules ...]
      Prints the AnalysisBundle as JSON: what the LLM reasons over (events, links, timeline,
      findings, hypotheses with confidence factors, and the confidence ceiling).
  investigator init --workdir <dir> --incident-file <file>
      Validate an incident and save it verbatim as <dir>/incident.txt (R17: nobody retypes it).
  investigator check --workdir <dir> -- mocklogs <args...>
      Allow/deny one command the AI wants to run (D31). Exit 0 = allowed, 1 = denied; JSON reasons.
  investigator run --workdir <dir> --reason "<why>" -- mocklogs <args...>
      The ONLY way the agent runs a fetch: check, then execute without a shell. Every attempt
      (allowed or denied) is appended to <dir>/actions.jsonl. Exit: the command's own code, or 1 if denied.
  investigator score --workdir <dir> --cause <event_id>
      The confidence factors and ceiling for an AI-proposed cause (D31).
  investigator validate --workdir <dir> --report <report.json>
      Check an AI report against the evidence. Exit 0 = valid, 1 = invalid (JSON errors).
  investigator render --workdir <dir> --report <report.json>
      Render a report as Markdown.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from investigator.adapters import FileSource
from investigator.correlation_keys import load_rules
from investigator.models import to_jsonable
from investigator.parsing import parse_all
from investigator.parsing.incident import IncidentError, parse_incident
from investigator.planner import plan

DEFAULT_RULES = Path(".claude/skills/incident-logs/SKILL.md")
INCIDENT_FILE = "incident.txt"


def cmd_plan(a) -> int:
    workdir = Path(a.workdir)
    incident_path = workdir / INCIDENT_FILE
    if not incident_path.is_file():
        print(f"error: {incident_path} not found (the runtime saves the incident there before planning)",
              file=sys.stderr)
        return 2
    try:
        rules = load_rules(a.rules)
    except (OSError, ValueError) as e:
        print(f"error: can't load correlation-key rules from {a.rules}: {e}", file=sys.stderr)
        return 2
    try:
        incident = parse_incident(incident_path.read_text(encoding="utf-8"), rules)
    except IncidentError as e:
        print(f"error: invalid incident: {e}", file=sys.stderr)
        return 2
    source = FileSource(workdir)
    result = plan(incident, parse_all(source), list(source.outputs()), str(workdir))
    print(json.dumps(to_jsonable(result), indent=2))
    return 0


def cmd_correlate(a) -> int:
    from investigator.pipeline import analyse_workdir
    workdir = Path(a.workdir)
    if not (workdir / INCIDENT_FILE).is_file():
        print(f"error: {workdir / INCIDENT_FILE} not found", file=sys.stderr)
        return 2
    try:
        bundle = analyse_workdir(workdir, load_rules(a.rules))
    except (OSError, ValueError) as e:  # IncidentError is a ValueError
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(to_jsonable(bundle), indent=2))
    return 0


def _load(a):
    from investigator.pipeline import prepare
    return prepare(Path(a.workdir), load_rules(a.rules))


def _verdict(a):
    from investigator.allowlist import load_allowlist, skills_dir_for
    from investigator.guard import check
    argv = list(a.command)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    p = _load(a)
    return argv, check(argv, p.incident, p.topology, str(Path(a.workdir)), load_allowlist(skills_dir_for(a.rules)))


def cmd_init(a) -> int:
    workdir, target = Path(a.workdir), Path(a.workdir) / INCIDENT_FILE
    try:
        text = Path(a.incident_file).read_text(encoding="utf-8")
        incident = parse_incident(text, load_rules(a.rules))
    except (OSError, ValueError) as e:
        print(f"error: invalid incident: {e}", file=sys.stderr)
        return 2
    if target.exists() and target.read_text(encoding="utf-8") != text:
        print(f"error: {target} already holds a different incident; use a new --workdir", file=sys.stderr)
        return 2
    workdir.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(json.dumps({"saved": str(target), "seed_app": incident.seed.app,
                      "business_key": incident.seed.business_key,
                      "inputs": {"app": incident.app is not None, "related_apps": sorted(incident.related_apps),
                                 "kafka": bool(incident.kafka_bootstrap), "db": bool(incident.db_host)}}, indent=2))
    return 0


def cmd_run(a) -> int:
    import subprocess
    from datetime import datetime, timezone
    try:
        argv, verdict = _verdict(a)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    record = {"ts": datetime.now(timezone.utc).isoformat(), "argv": argv, "reason": a.reason,
              "allowed": verdict.allowed, "denials": verdict.reasons}
    code = 1
    if verdict.allowed:
        proc = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=120)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        code = record["exit_code"] = proc.returncode
    else:
        print(json.dumps({"allowed": False, "shape": verdict.shape, "reasons": verdict.reasons}, indent=2))
    with open(Path(a.workdir) / "actions.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return code


def cmd_check(a) -> int:
    try:
        argv, verdict = _verdict(a)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"allowed": verdict.allowed, "shape": verdict.shape, "reasons": verdict.reasons}, indent=2))
    return 0 if verdict.allowed else 1


def cmd_score(a) -> int:
    from investigator.pipeline import score_in_workdir
    try:
        h = score_in_workdir(Path(a.workdir), load_rules(a.rules), a.cause)
    except KeyError:
        print(f"error: event {a.cause!r} isn't among the collected events", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(to_jsonable(h), indent=2))
    return 0


def cmd_validate(a) -> int:
    from investigator.pipeline import validate_report_in_workdir
    try:
        report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(json.dumps({"valid": False, "errors": [{"code": "missing_section", "path": "$",
                                                       "detail": f"not readable JSON: {e}"}]}, indent=2))
        return 1
    result = validate_report_in_workdir(Path(a.workdir), load_rules(a.rules), report)
    print(json.dumps({"valid": not result.errors, "errors": to_jsonable(result.errors)}, indent=2))
    return 0 if not result.errors else 1


def cmd_render(a) -> int:
    from investigator.pipeline import validate_report_in_workdir
    from investigator.report.render_md import render
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    result = validate_report_in_workdir(Path(a.workdir), load_rules(a.rules), report)
    if result.errors:
        print("error: the report doesn't validate; run `investigator validate` first", file=sys.stderr)
        return 1
    print(render(report, result.events), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator", description="Deterministic incident investigation (no LLM).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="list the next fetches for the incident in --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES), help="coordinator SKILL.md with the correlation-key table")
    s = sub.add_parser("correlate", help="print the analysis bundle for the incident in --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s = sub.add_parser("init", help="validate an incident and save it into --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s.add_argument("--incident-file", required=True)
    s = sub.add_parser("check", help="allow/deny one command the AI wants to run")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- mocklogs <args...>")
    s = sub.add_parser("run", help="check, then run one fetch command (the agent's only way to fetch)")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s.add_argument("--reason", required=True, help="why this command (recorded in actions.jsonl)")
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- mocklogs <args...>")
    s = sub.add_parser("score", help="confidence factors and ceiling for an AI-proposed cause")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s.add_argument("--cause", required=True, help="event_id of the proposed cause")
    for name, helptext in (("validate", "check an AI report against the evidence"),
                           ("render", "render a validated report as Markdown")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--workdir", required=True)
        s.add_argument("--rules", default=str(DEFAULT_RULES))
        s.add_argument("--report", required=True)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    return {"plan": cmd_plan, "correlate": cmd_correlate, "init": cmd_init, "check": cmd_check, "run": cmd_run,
            "score": cmd_score, "validate": cmd_validate, "render": cmd_render}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
