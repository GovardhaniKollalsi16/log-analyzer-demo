"""M8 robustness matrix: every scenario x every perturbation, end to end (planner loop -> bundle).

Each perturbation must leave the investigation's outcome unchanged: the same detectors fire,
the same kind of cause is found, and the same confidence ceiling results. Access denials are
the exception: they're expected to LOWER confidence, never raise it.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from investigator.adapters import FileSource
from investigator.correlation_keys import load_rules
from investigator.models import Confidence
from investigator.parsing import parse_all
from investigator.parsing.incident import parse_incident
from investigator.pipeline import analyse_workdir
from investigator.planner import plan
from mocklogs import cli as mock_cli, sso
from mocklogs.scenarios import SCENARIOS

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "incident-logs" / "SKILL.md"
RULES = load_rules(SKILL)
MODULES = {"upstream-timeout": "upstream_timeout", "db-config": "db_config",
           "consumer-processing": "consumer_processing", "ambiguous": "ambiguous"}
EXPECTED = {  # ground truth lives HERE (tests), never in investigator
    "upstream-timeout": ("kafka.broker.isr_shrink", Confidence.HIGH),
    "db-config": ("config.inconsistent", Confidence.HIGH),
    "consumer-processing": ("kafka.consumer.processing_failed", Confidence.HIGH),
    "ambiguous": (None, Confidence.INSUFFICIENT),
}


def rename_all(scenario: str) -> dict:
    """Map every base name role to something unrelated (derived names follow automatically)."""
    defaults = importlib.import_module(f"mocklogs.scenarios.{MODULES[scenario]}").DEFAULT_NAMES
    out = {}
    for i, (role, value) in enumerate(sorted(defaults.items())):
        if role == "bootstrap":
            out[role] = "bk-zeta:9099"
        elif role in ("cluster", "namespace", "db_host", "db_name"):
            out[role] = f"{role.replace('_', '')}-zeta"
        elif "." in value:
            out[role] = f"zq{i}.stream"
        else:
            out[role] = f"zsvc{i}-unit"
    return out


PERTURBATIONS = {
    "baseline": lambda s: {},
    "rename": lambda s: {"names": rename_all(s)},
    "time_shift": lambda s: {"t0": "2026-07-01T23:30:00Z"},
    "shuffle": lambda s: {"shuffle": True},
    "drop": lambda s: {"drop_rate": 0.3},
    "duplicate": lambda s: {"dup_rate": 0.3},
    "malformed": lambda s: {"malformed_rate": 0.2},
    "all_noise": lambda s: {"shuffle": True, "drop_rate": 0.2, "dup_rate": 0.2, "malformed_rate": 0.1},
}


def investigate(tmp_path, monkeypatch, capsys, scenario, knobs):
    monkeypatch.setenv("MOCKLOGS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MOCKLOGS_SCENARIO", scenario)
    monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps(knobs))
    sso.login()
    work = tmp_path / "work"
    work.mkdir()
    (work / "incident.txt").write_text("\n".join(mock_cli.run(["scenario", "incident"]).out))
    incident = parse_incident((work / "incident.txt").read_text(), RULES)
    for _ in range(10):
        source = FileSource(work)
        p = plan(incident, parse_all(source), list(source.outputs()), str(work))
        if p.done:
            break
        for step in p.steps:
            mock_cli.main(step.argv[1:])
    else:
        pytest.fail("planner did not converge in 10 rounds")
    capsys.readouterr()
    return analyse_workdir(work, RULES)


def outcome(bundle):
    by_id = {e.event_id: e for e in bundle.events}
    causes = sorted(by_id[h.cause_event_id].error_code for h in bundle.hypotheses)
    detectors = sorted({f.detector for f in bundle.findings if f.detector != "first_error_per_app"})
    return {"cap": bundle.confidence_cap, "causes": causes, "detectors": detectors}


@pytest.mark.parametrize("perturbation", sorted(PERTURBATIONS))
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_outcome_is_invariant(tmp_path, monkeypatch, capsys, scenario, perturbation):
    base = outcome(investigate(tmp_path / "base", monkeypatch, capsys, scenario, {}))
    expected_cause, expected_cap = EXPECTED[scenario]
    assert base["cap"] is expected_cap
    assert base["causes"] == ([expected_cause] if expected_cause else [])
    if perturbation == "baseline":
        return
    got = outcome(investigate(tmp_path / perturbation, monkeypatch, capsys, scenario,
                              PERTURBATIONS[perturbation](scenario)))
    assert got == base, f"{scenario} under {perturbation}: {got} != {base}"


DENIALS = {  # one entitlement gap per scenario that removes real evidence
    "upstream-timeout": ["config:seed_app"],
    "db-config": ["db:db_name"],
    "consumer-processing": ["logs:middle_app"],
}


@pytest.mark.parametrize("scenario", sorted(DENIALS))
def test_access_denial_never_raises_confidence(tmp_path, monkeypatch, capsys, scenario):
    base = outcome(investigate(tmp_path / "base", monkeypatch, capsys, scenario, {}))
    denied = outcome(investigate(tmp_path / "denied", monkeypatch, capsys, scenario,
                                 {"access_denied": DENIALS[scenario]}))
    assert denied["cap"].rank < base["cap"].rank


def test_renamed_incident_really_contains_no_original_names(tmp_path, monkeypatch, capsys):
    for scenario in sorted(SCENARIOS):
        defaults = importlib.import_module(f"mocklogs.scenarios.{MODULES[scenario]}").DEFAULT_NAMES
        monkeypatch.setenv("MOCKLOGS_SCENARIO", scenario)
        monkeypatch.setenv("MOCKLOGS_KNOBS", json.dumps({"names": rename_all(scenario)}))
        text = "\n".join(mock_cli.run(["scenario", "incident"]).out)
        leaked = [v for v in defaults.values() if v in text and v != "apps"]
        assert not leaked, (scenario, leaked)
