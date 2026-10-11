"""Scenario registry. The scenario name is chosen by the user/harness, never by the agent (R20)."""

from __future__ import annotations

from typing import Callable, Dict

from mocklogs.scenarios import ambiguous, consumer_processing, db_config, upstream_timeout
from mocklogs.scenarios.base import ScenarioKnobs
from mocklogs.world import World

SCENARIOS: Dict[str, Callable[[ScenarioKnobs], World]] = {
    "upstream-timeout": upstream_timeout.generate,
    "db-config": db_config.generate,
    "consumer-processing": consumer_processing.generate,
    "ambiguous": ambiguous.generate,
}


def load(name: str, knobs: ScenarioKnobs = ScenarioKnobs()) -> World:
    try:
        generator = SCENARIOS[name]
    except KeyError:
        raise ValueError(f"unknown scenario {name!r}; known: {sorted(SCENARIOS)}") from None
    return generator(knobs)
