"""The agent reads SKILL.md, so it must not hint at any scenario's answer."""

from __future__ import annotations

from pathlib import Path

from _vocabulary import SCENARIO_VOCABULARY

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "incident-logs" / "SKILL.md"


def test_skill_exists_with_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: incident-logs\n")


def test_skill_never_mentions_scenario_names():
    text = SKILL.read_text(encoding="utf-8").lower()
    found = [w for w in SCENARIO_VOCABULARY if w in text]
    assert not found, f"SKILL.md mentions scenario vocabulary: {found}"
