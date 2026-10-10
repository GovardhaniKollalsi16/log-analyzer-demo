"""The agent reads every skill file, so none may hint at a scenario's answer."""

from __future__ import annotations

from pathlib import Path

import pytest

from _vocabulary import SCENARIO_VOCABULARY

SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"
EXPECTED_SKILLS = [
    "incident-logs",        # coordinator
    "incident-app-logs",
    "incident-app-config",
    "incident-kafka",
    "incident-db-logs",
]


def test_every_expected_skill_exists_and_nothing_unexpected():
    found = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
    assert found == sorted(EXPECTED_SKILLS)


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_skill_frontmatter_names_itself(name):
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith(f"---\nname: {name}\ndescription: ")


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_skill_never_mentions_scenario_names(name):
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8").lower()
    found = [w for w in SCENARIO_VOCABULARY if w in text]
    assert not found, f"{name}/SKILL.md mentions scenario vocabulary: {found}"


@pytest.mark.parametrize("name", EXPECTED_SKILLS[1:])
def test_component_skills_cover_login_inputs_commands_and_signals(name):
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    for heading in ("## 1. Logging in", "## 2. Where the inputs come from", "## 3. Command",
                    "## 4. Output format", "## 5. What to"):
        assert heading in text, f"{name} is missing section {heading!r}"
    assert "never run `mocklogs sso login`" in text
    assert "--save-dir <workdir>" in text
