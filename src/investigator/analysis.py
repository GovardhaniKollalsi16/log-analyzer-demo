"""Hypotheses, confidence factors, the confidence ceiling, and the AnalysisBundle (M7_RULES §2–§4).

The code scores candidate causes; it never picks the root cause. The ceiling is the most
the report may claim, enforced by the validator (M9).
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from investigator.adapters.base import RawOutput
from investigator.correlation import CorrelationResult
from investigator.detectors import INFORMATIONAL, Context, run_all
from investigator.models import (AnalysisBundle, AppTopology, Confidence, ConfidenceFactor, CoverageGap, Direction,
                                 Event, FactorName, FactorValue, FetchStep, Finding, GapReason, Hypothesis, Incident,
                                 LinkKind, Severity, Source)
from investigator.parsing.dispatch import command_shape
from investigator.timeline import build_timeline

V = FactorValue
_RANK = {V.STRONG: 3, V.PARTIAL: 2, V.WEAK: 1, V.ABSENT: 0}
STRONG_LINKS = {LinkKind.EXACT_ID, LinkKind.BUSINESS_KEY, LinkKind.SAME_OCCURRENCE}


@dataclass
class _Chain:
    findings: List[Finding]
    event_ids: Set[str]


# --- hypotheses ---------------------------------------------------------------------------

def _chains(findings: List[Finding]) -> List[_Chain]:
    """Findings that share an event, or repeat one detector's pattern on the same client/resource,
    belong to one chain. Informational findings are excluded."""
    work = [f for f in findings if f.detector not in INFORMATIONAL]
    parent = list(range(len(work)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    owner: Dict[str, int] = {}
    for i, f in enumerate(work):
        # repeated occurrences of one pattern on one client/resource are one chain, not rivals
        subject = f.attrs.get("key") or f.attrs.get("resource") or f.attrs.get("at")
        tokens = list(f.event_ids) + ([f"{f.detector}|{subject}"] if subject else [])
        for token in tokens:
            if token in owner:
                parent[find(i)] = find(owner[token])
            else:
                owner[token] = i
    groups: Dict[int, List[Finding]] = {}
    for i, f in enumerate(work):
        groups.setdefault(find(i), []).append(f)
    return [_Chain(fs, {e for f in fs for e in f.event_ids}) for fs in groups.values()]


def _cause_of(chain: _Chain, by_id: Dict[str, Event], seed: Event) -> Optional[Event]:
    candidates = [by_id[e] for e in chain.event_ids
                  if e != seed.event_id and by_id[e].severity in (Severity.ERROR, Severity.SYMPTOM, Severity.ANOMALY)
                  and (by_id[e].ts_utc is None or by_id[e].ts_utc <= seed.ts_utc)]
    # config (no timestamp) is state that existed before the incident, so it sorts first
    return min(candidates, key=lambda e: (e.ts_utc is not None, e.ts_utc, e.event_id), default=None)


# --- factors --------------------------------------------------------------------------------

def _id_linkage(cause: Event, seed: Event, cor: CorrelationResult, seed_group: Set[str],
                in_window: bool) -> ConfidenceFactor:
    name = FactorName.ID_LINKAGE
    if cause.source is Source.APP_CONFIG and cause.app == seed.app:
        return ConfidenceFactor(name, V.STRONG, "the cause is the seed app's own config")
    by_id = {e.event_id: e for e in cor.events}
    error_named = {r for eid in seed_group if eid in cor.resources and by_id[eid].severity is Severity.ERROR
                   for r in cor.resources[eid]}
    strong: Dict[str, List[str]] = {}
    anyl: Dict[str, List[str]] = {}
    for link in cor.links:
        shared = set(cor.resources.get(link.a, [])) & set(cor.resources.get(link.b, []))
        is_strong = link.kind in STRONG_LINKS or (link.kind is LinkKind.RESOURCE and bool(shared & error_named))
        for x, y in ((link.a, link.b), (link.b, link.a)):
            anyl.setdefault(x, []).append(y)
            if is_strong:
                strong.setdefault(x, []).append(y)

    def reaches(graph: Dict[str, List[str]]) -> bool:
        seen, queue = {seed.event_id}, deque([seed.event_id])
        while queue:
            x = queue.popleft()
            if x == cause.event_id:
                return True
            for y in graph.get(x, []):
                if y not in seen:
                    seen.add(y)
                    queue.append(y)
        return False
    if reaches(strong):
        return ConfidenceFactor(name, V.STRONG, "linked to the seed by IDs, the business key, or a topic-partition named by an ERROR")
    if reaches(anyl):
        return ConfidenceFactor(name, V.PARTIAL, "linked to the seed only through a thread segment or a weaker topic-partition link")
    if in_window:
        return ConfidenceFactor(name, V.WEAK, "no link path to the seed; only close in time")
    return ConfidenceFactor(name, V.ABSENT, "not in the seed's group")


def relevant_gaps(gaps: List[CoverageGap], topo: Optional[AppTopology]) -> List[CoverageGap]:
    out = []
    for g in gaps:
        if g.component is Source.DB and g.reason is GapReason.MISSING_INPUT and not (topo and topo.databases):
            continue  # no DB declared for the seed app: a missing `db:` line doesn't matter
        out.append(g)
    return out


def _coverage(gaps: List[CoverageGap], incident: Incident, topo: Optional[AppTopology]) -> ConfidenceFactor:
    name, seed = FactorName.TRAVERSAL_COVERAGE, incident.seed
    rel = relevant_gaps(gaps, topo)
    upstream = set(topo.upstream_apps) if topo else set()
    downstream = set(topo.downstream_apps) if topo else set()
    if any(g.component is Source.APP and g.target == seed.app for g in rel):
        return ConfidenceFactor(name, V.ABSENT, "the seed app's own logs are missing")
    weak = [g for g in rel if g.component is Source.KAFKA or g.target in (f"{seed.app}-config", "related apps")
            or (g.component is Source.APP and g.target in upstream)]
    if weak:
        return ConfidenceFactor(name, V.WEAK, "gap on " + ", ".join(sorted({f"{g.target} ({g.reason.value})" for g in weak})))
    partial = [g for g in rel if (g.component is Source.APP and g.target in downstream) or g.component is Source.DB]
    if partial:
        return ConfidenceFactor(name, V.PARTIAL, "gap on " + ", ".join(sorted({f"{g.target} ({g.reason.value})" for g in partial})))
    return ConfidenceFactor(name, V.STRONG, "no relevant gaps")


def _precedence(cause: Event, effects: List[Event], seed: Event) -> ConfidenceFactor:
    name = FactorName.TEMPORAL_PRECEDENCE
    if cause.ts_utc is None:
        return ConfidenceFactor(name, V.STRONG, "the cause is configuration that was in place before the incident")
    if cause.ts_utc > seed.ts_utc:
        return ConfidenceFactor(name, V.ABSENT, "the cause comes after the seed")
    if all(e.ts_utc is None or cause.ts_utc <= e.ts_utc for e in effects):
        return ConfidenceFactor(name, V.STRONG, "the cause precedes every effect and the seed")
    return ConfidenceFactor(name, V.WEAK, "the cause precedes the seed but not every effect")


def _ceiling(factors: List[ConfidenceFactor]) -> Confidence:
    by = {f.name: f.value for f in factors}
    if V.ABSENT in (by[FactorName.ID_LINKAGE], by[FactorName.TEMPORAL_PRECEDENCE], by[FactorName.TRAVERSAL_COVERAGE]):
        return Confidence.INSUFFICIENT
    if V.WEAK in by.values():
        return Confidence.LOW
    if V.PARTIAL in by.values():
        return Confidence.MEDIUM
    return Confidence.HIGH


def build_hypotheses(findings: List[Finding], ctx: Context, gaps: List[CoverageGap]) -> List[Hypothesis]:
    seed = ctx.by_id[ctx.incident.seed.event_id]
    coverage = _coverage(gaps, ctx.incident, ctx.topology)
    hyps: List[Tuple[Hypothesis, ConfidenceFactor]] = []
    for chain in sorted(_chains(findings), key=lambda c: min(c.event_ids)):
        cause = _cause_of(chain, ctx.by_id, seed)
        if cause is None:
            continue
        effects = sorted({e for e in chain.event_ids | {seed.event_id} if e != cause.event_id},
                         key=lambda e: (ctx.by_id[e].ts_utc is None, ctx.by_id[e].ts_utc, e))
        linkage = _id_linkage(cause, seed, ctx.cor, ctx.seed_group, ctx.in_window(cause))
        precedence = _precedence(cause, [ctx.by_id[e] for e in effects], seed)
        where = cause.app or cause.component or cause.source.value
        h = Hypothesis(hyp_id=f"h-{len(hyps) + 1}", cause_event_id=cause.event_id,
                       finding_ids=sorted(f.finding_id for f in chain.findings), effect_event_ids=effects,
                       summary=f"{cause.error_code} in {where} explains {len(effects)} event(s)",
                       factors=[linkage, coverage, precedence])
        hyps.append((h, linkage))
    for h, linkage in hyps:
        rivals = [l for other, l in hyps if other is not h]
        if not rivals:
            comp = ConfidenceFactor(FactorName.COMPETING_HYPOTHESES, V.STRONG, "the only hypothesis")
        elif any(_RANK[l.value] >= _RANK[linkage.value] for l in rivals):
            comp = ConfidenceFactor(FactorName.COMPETING_HYPOTHESES, V.WEAK, "a rival is linked at least as strongly")
        else:
            comp = ConfidenceFactor(FactorName.COMPETING_HYPOTHESES, V.PARTIAL, "rivals exist but are linked more weakly")
        h.factors.append(comp)
        h.ceiling = _ceiling(h.factors)
    return [h for h, _ in hyps]


# --- bundle ---------------------------------------------------------------------------------

def traversal_of(outputs: List[RawOutput]) -> List[FetchStep]:
    steps = []
    for i, out in enumerate(outputs, start=1):
        shape = command_shape(out.argv)
        component, _, target = shape if shape else (Source.APP, None, "?")
        steps.append(FetchStep(order=i, component=component, target=target, argv=list(out.argv),
                               reason=f"ran, exit code {out.exit_code}", direction=Direction.SEED))
    return steps


def build_bundle(incident: Incident, cor: CorrelationResult, topology: Optional[AppTopology],
                 outputs: List[RawOutput], gaps: List[CoverageGap]) -> AnalysisBundle:
    ctx = Context(incident, cor, topology, outputs)
    findings = run_all(ctx)
    hypotheses = build_hypotheses(findings, ctx, gaps)
    cited = {e for f in findings for e in f.event_ids} | {h.cause_event_id for h in hypotheses}
    config = {e.event_id for e in cor.events if e.source is Source.APP_CONFIG and e.app == incident.seed.app}
    # copies are dropped to avoid double counting, unless a finding or hypothesis cites them
    keep = (ctx.seed_group | cited | config) - (set(cor.copies) - cited)
    events = [e for e in cor.events if e.event_id in keep]
    groups = [g for g in cor.groups if g.group_id == cor.seed_group or set(g.event_ids) & cited]
    best = max(hypotheses, key=lambda h: h.ceiling.rank, default=None)
    digest = hashlib.sha1("|".join([incident.seed.event_id] + sorted(o.name for o in outputs)).encode()).hexdigest()
    return AnalysisBundle(
        bundle_id=f"b-{digest[:12]}",
        seed=incident.seed,
        topology=topology,
        traversal=traversal_of(outputs),
        coverage_gaps=gaps,
        events=events,
        groups=groups,
        timeline=build_timeline(events).entries,
        findings=findings,
        hypotheses=hypotheses,
        factors=list(best.factors) if best else [],
        confidence_cap=best.ceiling if best else Confidence.INSUFFICIENT,
    )
