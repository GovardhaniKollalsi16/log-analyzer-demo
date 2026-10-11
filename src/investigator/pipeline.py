"""Everything deterministic, end to end, for one workdir: parse -> classify -> topology ->
correlate -> detectors -> hypotheses -> bundle. Used by `investigator correlate` and the agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from investigator.adapters import FileSource
from investigator.adapters.base import RawOutput
from investigator.analysis import build_bundle, score_cause
from investigator.classify import classify
from investigator.correlation import CorrelationResult, correlate
from investigator.correlation_keys import KeyRule
from investigator.detectors import Context
from investigator.models import AnalysisBundle, AppTopology, CoverageGap, Hypothesis, Incident
from investigator.parsing import parse_all
from investigator.parsing.incident import parse_incident
from investigator.planner import plan, topology_of

INCIDENT_FILE = "incident.txt"


@dataclass
class Prepared:
    incident: Incident
    cor: CorrelationResult
    topology: Optional[AppTopology]
    outputs: List[RawOutput]
    gaps: List[CoverageGap]


def prepare(workdir: Union[str, Path], rules: List[KeyRule]) -> Prepared:
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
    return Prepared(incident, cor, topology, outputs, gaps)


def analyse_workdir(workdir: Union[str, Path], rules: List[KeyRule]) -> AnalysisBundle:
    p = prepare(workdir, rules)
    return build_bundle(p.incident, p.cor, p.topology, p.outputs, p.gaps)


def score_in_workdir(workdir: Union[str, Path], rules: List[KeyRule], cause_event_id: str) -> Hypothesis:
    """`investigator score`: the M7 factors and ceiling for an AI-proposed cause (D31)."""
    p = prepare(workdir, rules)
    bundle = build_bundle(p.incident, p.cor, p.topology, p.outputs, p.gaps)
    ctx = Context(p.incident, p.cor, p.topology, p.outputs)
    if cause_event_id not in ctx.by_id:
        raise KeyError(cause_event_id)
    return score_cause(ctx, p.gaps, cause_event_id, bundle.hypotheses)


def validate_report_in_workdir(workdir: Union[str, Path], rules: List[KeyRule], report) -> "ReportCheck":
    """Validate an AI report against the evidence collected in `workdir` (M9)."""
    from investigator.report.validate import validate
    p = prepare(workdir, rules)
    bundle = build_bundle(p.incident, p.cor, p.topology, p.outputs, p.gaps)
    ctx = Context(p.incident, p.cor, p.topology, p.outputs)
    errors = validate(report, bundle, ctx.by_id, lambda eid: score_cause(ctx, p.gaps, eid, bundle.hypotheses))
    return ReportCheck(bundle=bundle, events=ctx.by_id, errors=errors)


@dataclass
class ReportCheck:
    bundle: AnalysisBundle
    events: dict
    errors: list
