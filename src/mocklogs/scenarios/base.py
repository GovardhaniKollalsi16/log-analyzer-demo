"""Scenario knobs and the deterministic helpers every generator shares."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, FrozenSet

DEFAULT_T0 = datetime(2026, 3, 14, 9, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ScenarioKnobs:
    """Perturbations for robustness tests (D8). Defaults reproduce the canonical scenario.

    names       role -> name overrides, e.g. {"seed_app": "svc-q"}; renames apps, topics,
                groups, cluster, namespace, DB, threads' owning app, instances.
    t0          scenario start; shifting it shifts every timestamp.
    drop_rate / dup_rate / malformed_rate
                applied at render time to NON-critical lines only.
    shuffle     shuffle line order within each command's output.
    access_denied
                entitlement gaps, e.g. {"config:<seed_app>"}; role names are resolved.
    omit_inputs incident lines to leave out: subset of {"app", "kafka", "db", "related"}.
    """

    seed: int = 7
    names: Dict[str, str] = field(default_factory=dict)
    t0: datetime = DEFAULT_T0
    drop_rate: float = 0.0
    dup_rate: float = 0.0
    malformed_rate: float = 0.0
    shuffle: bool = False
    access_denied: FrozenSet[str] = frozenset()
    omit_inputs: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        for rate in (self.drop_rate, self.dup_rate, self.malformed_rate):
            if not 0.0 <= rate < 1.0:
                raise ValueError("rates must be in [0, 1)")
        if self.t0.tzinfo is None:
            raise ValueError("t0 must be timezone-aware")


def make_rng(seed: int, salt: str = "") -> random.Random:
    return random.Random(f"{seed}:{salt}")


def short_id(rng: random.Random, prefix: str, n: int = 6) -> str:
    return prefix + "".join(rng.choice("0123456789abcdef") for _ in range(n))


def resolve_names(defaults: Dict[str, str], knobs: ScenarioKnobs) -> Dict[str, str]:
    unknown = set(knobs.names) - set(defaults)
    if unknown:
        raise ValueError(f"unknown name roles: {sorted(unknown)}")
    return {**defaults, **knobs.names}


def resolve_denied(knobs: ScenarioKnobs, names: Dict[str, str]) -> set:
    """Allow knobs to say "config:seed_app" (role) or "config:<actual name>"."""
    out = set()
    for item in knobs.access_denied:
        kind, _, target = item.partition(":")
        out.add(f"{kind}:{names.get(target, target)}")
    return out
