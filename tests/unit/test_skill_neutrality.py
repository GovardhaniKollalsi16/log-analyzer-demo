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
    for heading in ("## 1. Logging in", "## 2. Required inputs", "## 3. Command",
                    "## 4. Output format", "## 5. What to"):
        assert heading in text, f"{name} is missing section {heading!r}"
    assert "never run `mocklogs sso login`" in text
    assert "--save-dir <workdir>" in text
    # "No input, no access" (user rule, 2026-10-10)
    assert "**If any required input is missing, don't run any command from this skill.**" in text
    assert "`missing_input`" in text


def test_coordinator_states_no_input_no_access():
    text = (SKILLS_DIR / "incident-logs" / "SKILL.md").read_text(encoding="utf-8")
    assert "**No input, no access.**" in text
    assert "INCIDENT\nseed:" in text  # the incident message format is documented


def test_coordinator_correlation_key_table_is_machine_readable():
    import json
    import re
    text = (SKILLS_DIR / "incident-logs" / "SKILL.md").read_text(encoding="utf-8")
    block = re.search(r"```json\n(\{\"correlation_keys\".*?)\n```", text, re.S)
    assert block, "correlation_keys JSON block missing"
    rules = json.loads(block.group(1))["correlation_keys"]
    by_prefix = {r["source_class_prefix"]: r for r in rules}
    assert by_prefix["Order"]["key"] == "order_id"
    assert by_prefix["Product"]["key"] == "product_id"
    for r in rules:
        assert set(r["stored_as"]) == {"app_logs", "kafka", "db"}
