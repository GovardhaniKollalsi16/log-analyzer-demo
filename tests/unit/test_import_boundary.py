"""Guards against scenario knowledge leaking into the analysis code.

`investigator` must never import `mocklogs`, and must never mention the synthetic
service/resource names that the scenarios use (decision D6). If a detector needs a
service name to work, it is hardcoding the answer.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
INVESTIGATOR = SRC / "investigator"

# D6 synthetic names. These may appear in mocklogs and tests, never in investigator.
SCENARIO_VOCABULARY = [
    "order-api",
    "fulfillment-worker",
    "notification-worker",
    "edge-gateway",
    "partner-pricing",
    "orders.events",
    "pricing.events",
    "fulfillment-consumers",
    "appdb",
]


def _python_files() -> list[Path]:
    files = sorted(INVESTIGATOR.rglob("*.py"))
    assert files, f"no python files found under {INVESTIGATOR}"
    return files


def test_investigator_never_imports_mocklogs():
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "mocklogs" or n.startswith("mocklogs.") for n in names):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, f"investigator imports mocklogs at: {offenders}"


def test_investigator_never_mentions_scenario_names():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8").lower()
        offenders += [f"{path.relative_to(SRC)}: {w}" for w in SCENARIO_VOCABULARY if w in text]
    assert not offenders, f"scenario vocabulary found in investigator: {offenders}"
