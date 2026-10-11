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


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_skill_never_contains_scenario_story_lines(name):
    from _vocabulary import SCENARIO_STORY_PHRASES
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    found = [p for p in SCENARIO_STORY_PHRASES if p in text]
    assert not found, f"{name}/SKILL.md contains scenario story text: {found}"


def test_skill_samples_are_real_and_current():
    """Samples must be exactly what mocklogs prints for the neutral fixture."""
    from mocklogs import skill_samples
    samples = skill_samples.generate()
    used = []
    for name in EXPECTED_SKILLS:
        path = SKILLS_DIR / name / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        used += [m.group("key") for m in skill_samples.BLOCK.finditer(text)]
        assert skill_samples.apply(text, samples) == text, (
            f"{name}/SKILL.md samples are stale; run: python -m mocklogs.skill_samples --write")
    assert sorted(used) == sorted(samples), "every generated sample is used exactly once"
    assert "PENDING" not in "".join((SKILLS_DIR / n / "SKILL.md").read_text() for n in EXPECTED_SKILLS)


@pytest.mark.parametrize("name", EXPECTED_SKILLS[1:])
def test_component_skills_document_exit_codes_3_4_5(name):
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    for code in ("exit code **3**", "exit code **4**", "exit code **5**"):
        assert code in text, f"{name} doesn't document {code}"
    assert "`not_found`" in text


def test_coordinator_forbids_inferring_apps_from_names():
    text = (SKILLS_DIR / "incident-logs" / "SKILL.md").read_text(encoding="utf-8")
    assert "**Never infer an app from a name.**" in text
    kafka = (SKILLS_DIR / "incident-kafka" / "SKILL.md").read_text(encoding="utf-8")
    assert "is the app name" not in kafka and "Never derive an app from a client ID" in kafka


def test_collect_first_and_kafka_collection_scope():
    coord = (SKILLS_DIR / "incident-logs" / "SKILL.md").read_text(encoding="utf-8")
    assert "**Collect first, assess later.**" in coord
    kafka = (SKILLS_DIR / "incident-kafka" / "SKILL.md").read_text(encoding="utf-8")
    for item in ("**Incoming:**", "**Outgoing:**", "**Retries:**", "**Topic errors and connection timeouts:**"):
        assert item in kafka, item
    assert "kafka-consumer-groups" not in kafka  # lag/all-groups are not part of collection (user, 2026-10-10)


def test_coordinator_procedure_is_an_investigation_with_guardrails():
    """D31: the agent investigates; plan = suggestions; every fetch via `investigator run`; causes scored."""
    text = (SKILLS_DIR / "incident-logs" / "SKILL.md").read_text(encoding="utf-8")
    assert "## 6. Procedure: investigate" in text
    for cmd in ("investigator init --workdir", "investigator plan --workdir", "investigator run --workdir",
                "investigator correlate --workdir", "investigator score --workdir", "investigator validate --workdir"):
        assert cmd in text, cmd
    assert "exactly as given, in order" not in text  # the old "run the planner's steps exactly" rule is gone
    assert "## 7. Report contract" in text and "confidence_above_ceiling" in text


def documented_commands():
    """Every `mocklogs ...` command written in a component skill's code blocks (sample output excluded)."""
    import re
    for name in EXPECTED_SKILLS[1:]:
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        for block in re.findall(r"```\n(.*?)```", text, re.S):
            joined = block.replace("\\\n", " ")  # join shell line continuations
            for line in joined.splitlines():
                if line.strip().startswith("mocklogs "):
                    yield name, line.split()[1:]


def test_every_documented_command_is_allowlisted_and_sso_login_never_is():
    from investigator.allowlist import load_allowlist
    al = load_allowlist(SKILLS_DIR)
    assert not any(shape.startswith("sso") for shape in al.flags)
    checked = 0
    for name, words in documented_commands():
        shape = " ".join(words[:2]) if words[0] in ("kubectl", "kafka", "db") else words[0]
        assert shape in al.flags, (name, shape)
        flags = {w.split("=")[0] for w in words if w.startswith("-")}
        assert flags <= al.flags[shape], (name, shape, flags - al.flags[shape])
        checked += 1
    assert checked >= 10
