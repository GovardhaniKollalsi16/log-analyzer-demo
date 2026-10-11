"""`investigator`: the deterministic side of the investigation (no LLM).

  investigator plan --workdir <dir> [--rules <coordinator SKILL.md>]
      Reads <dir>/incident.txt and everything saved in <dir>/raw/, prints the next
      fetches as JSON: {"steps": [...argv...], "gaps": [...], "done": bool, ...}.
  investigator correlate --workdir <dir> [--rules ...]
      Prints the AnalysisBundle as JSON: what the LLM reasons over (events, links, timeline,
      findings, hypotheses with confidence factors, and the confidence ceiling).
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator", description="Deterministic incident investigation (no LLM).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="list the next fetches for the incident in --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES), help="coordinator SKILL.md with the correlation-key table")
    s = sub.add_parser("correlate", help="print the analysis bundle for the incident in --workdir")
    s.add_argument("--workdir", required=True)
    s.add_argument("--rules", default=str(DEFAULT_RULES))
    return p


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    return {"plan": cmd_plan, "correlate": cmd_correlate}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
