"""Everything deterministic, end to end, for one workdir: parse -> classify -> topology ->
correlate -> detectors -> hypotheses -> bundle. Used by `investigator correlate` and the agent loop."""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

from investigator.adapters import FileSource
from investigator.analysis import build_bundle
from investigator.classify import classify
from investigator.correlation import correlate
from investigator.correlation_keys import KeyRule
from investigator.models import AnalysisBundle, CoverageGap
from investigator.parsing import parse_all
from investigator.parsing.incident import parse_incident
from investigator.planner import plan, topology_of

INCIDENT_FILE = "incident.txt"


def analyse_workdir(workdir: Union[str, Path], rules: List[KeyRule]) -> AnalysisBundle:
    workdir = Path(workdir)
    incident = parse_incident((workdir / INCIDENT_FILE).read_text(encoding="utf-8"), rules)
    source = FileSource(workdir)
    outputs = list(source.outputs())
    parsed = parse_all(source)
    topology = topology_of(incident, parsed)
    # coverage gaps = refusals seen in the outputs + steps the planner couldn't run (missing inputs)
    planned = plan(incident, parsed, outputs, str(workdir))
    gaps: List[CoverageGap] = []
    for g in parsed.gaps + planned.gaps:
        if g not in gaps:
            gaps.append(g)
    cor = correlate(classify(parsed.events), incident, topology)
    return build_bundle(incident, cor, topology, outputs, gaps)
