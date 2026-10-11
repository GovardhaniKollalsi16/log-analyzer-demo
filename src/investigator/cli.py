"""`investigator`: the deterministic side of the investigation (no LLM).

  investigator plan --workdir <dir> [--rules <coordinator SKILL.md>]
      Reads <dir>/incident.txt and everything saved in <dir>/raw/, prints the next
      fetches as JSON: {"steps": [...argv...], "gaps": [...], "done": bool, ...}.
  investigator correlate --workdir <dir> [--rules ...]
      Prints the AnalysisBundle as JSON: what the LLM reasons over (events, links, timeline,
      findings, hypotheses with confidence factors, and the confidence ceiling).
  investigator check --workdir <dir> -- mocklogs <args...>
      Allow/deny one command the AI wants to run (D31). Exit 0 = allowed, 1 = denied; JSON reasons.
  investigator score --workdir <dir> --cause <event_id>
      The confidence factors and ceiling for an AI-proposed cause (D31).
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


def cmd_check(a) -> int:
    from investigator.guard import check
    argv = list(a.command)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    try:
        p = _load(a)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    verdict = check(argv, p.incident, p.topology, str(Path(a.workdir)))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator", description="Deterministic incident investigation (no LLM).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="list the next fetches for the incident in --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES), help="coordinator SKILL.md with the correlation-key table")
    s = sub.add_parser("correlate", help="print the analysis bundle for the incident in --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s = sub.add_parser("check", help="allow/deny one command the AI wants to run")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- mocklogs <args...>")
    s = sub.add_parser("score", help="confidence factors and ceiling for an AI-proposed cause")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    s.add_argument("--cause", required=True, help="event_id of the proposed cause")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    return {"plan": cmd_plan, "correlate": cmd_correlate, "check": cmd_check, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
