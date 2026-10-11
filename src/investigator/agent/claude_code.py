"""The Claude Code path (D32): the `incident-investigator` subagent, run headless on the user's own
Claude login (`claude -p`), never an API key.

  incident file -> `investigator init` (verbatim, R17) -> `claude -p --agent incident-investigator`
  with the incident as the first message (D19) -> the subagent investigates with `investigator …`
  commands only (PreToolUse hook + `investigator run`) and writes <workdir>/report.json ->
  the harness validates that file itself; missing or invalid -> the INSUFFICIENT fallback.

Permissions: `dontAsk` denies anything not pre-approved; approved are only `investigator <subcommand>`
for the allowed subcommands and edits under the workdir; reads of the repo's code, tests, docs and runs
are denied. User settings and MCP servers are not loaded, so nothing on this machine
widens that. ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are removed from the environment, so the run
uses the `/login` subscription. Every stream event goes to runs/<timestamp>-<label>.jsonl.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from investigator.agent.loop import MAX_REPORT_ATTEMPTS, AgentResult, Transcript
from investigator.correlation_keys import load_rules
from investigator.models import to_jsonable
from investigator.parsing.incident import parse_incident
from investigator.pipeline import INCIDENT_FILE, analyse_workdir, validate_report_in_workdir
from investigator.report.model import fallback_report
from investigator.report.render_md import render

PROJECT_DIR = Path(__file__).resolve().parents[3]
AGENT = "incident-investigator"
TIMEOUT_S = 20 * 60
SECRET_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


# Subcommands the agent may run; `agent` (a nested run) is not one of them. Same set as the hook's.
SUBCOMMANDS = ("init", "plan", "run", "correlate", "check", "score", "validate", "render")
# Repo folders the agent must not read: the mock scenarios' code, the tests and earlier runs hold the answers.
HIDDEN_DIRS = ("src", "tests", "docs", "runs")
HOOK = Path(".claude") / "hooks" / "allowlist_guard.py"


def build_settings(project_dir: Path) -> str:
    """The allowlist hook as session settings, by absolute path. The agent's frontmatter also declares it,
    but the first live run showed that one didn't fire (AI_NOTES), so the hook doesn't rely on it."""
    hook = {"type": "command", "command": str(project_dir / HOOK), "args": []}
    return json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [hook]}]}})


def build_command(claude_bin: str, workdir: Path, project_dir: Path = PROJECT_DIR) -> List[str]:
    """The permission rules are the primary limit: they hold even if the hook doesn't run."""
    return [claude_bin, "-p", "--agent", AGENT,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk",
            "--setting-sources", "project", "--strict-mcp-config",
            "--settings", build_settings(project_dir),
            "--add-dir", str(workdir),
            "--disallowedTools", "Bash(investigator agent *)",
            *[f"Read(/{project_dir / d}/**)" for d in HIDDEN_DIRS],
            "--allowedTools", *[f"Bash(investigator {c} *)" for c in SUBCOMMANDS], f"Edit(/{workdir}/**)"]


def build_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {k: v for k, v in (base if base is not None else os.environ).items() if k not in SECRET_ENV}
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"  # the venv's `investigator`
    return env


def first_message(workdir: Path, incident_text: str) -> str:
    return (f"workdir: {workdir}\n\nInvestigate this incident (saved verbatim at {workdir / INCIDENT_FILE}). "
            f"Write the report to {workdir / 'report.json'} and validate it.\n\n{incident_text}")


def _is_validate(command: str) -> bool:
    words = command.split()
    return words[:2] == ["investigator", "validate"] and "--report" in words and "--help" not in words


def _report_attempts(events: List[Dict[str, Any]]) -> int:
    n = 0
    for e in events:
        for block in ((e.get("message") or {}).get("content") or []) if e.get("type") == "assistant" else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash" \
                    and _is_validate(str((block.get("input") or {}).get("command", ""))):
                n += 1
    return n


def run_claude_code(incident_file: Union[str, Path], workdir: Union[str, Path], rules_path: Union[str, Path],
                    runs_dir: Union[str, Path], label: str, claude_bin: str = "claude",
                    project_dir: Path = PROJECT_DIR, timeout_s: int = TIMEOUT_S,
                    env: Optional[Dict[str, str]] = None) -> AgentResult:
    workdir = Path(workdir).resolve()
    rules = load_rules(Path(rules_path))
    incident_text = Path(incident_file).read_text(encoding="utf-8")
    parse_incident(incident_text, rules)  # validate before starting
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / INCIDENT_FILE).write_text(incident_text, encoding="utf-8")  # verbatim (R17)
    report_path = workdir / "report.json"
    if report_path.exists():
        raise FileExistsError(f"{report_path} exists; use a new workdir")

    transcript = Transcript(Path(runs_dir), label)
    cmd, prompt = build_command(claude_bin, workdir, project_dir), first_message(workdir, incident_text)
    transcript.write("start", label=label, workdir=str(workdir), incident=incident_text, provider="claude-code",
                     command=cmd)
    transcript.write("user", content=prompt)

    events: List[Dict[str, Any]] = []
    reason: Optional[str] = None
    try:
        proc = subprocess.Popen(cmd, cwd=str(project_dir), env=build_env(env), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        proc, reason = None, f"couldn't start Claude Code: {e}"
    if proc is not None:
        try:
            out, err = proc.communicate(prompt, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            reason = f"Claude Code timed out after {timeout_s}s"
        for line in out.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                transcript.write("claude_stdout", line=line)
                continue
            events.append(event)
            transcript.write("claude_event", event=event)
        if err.strip():
            transcript.write("claude_stderr", text=err[-4000:])
        if reason is None and proc.returncode != 0:
            reason = f"Claude Code exited with code {proc.returncode}"

    result_event = next((e for e in reversed(events) if e.get("type") == "result"), {})
    attempts = _report_attempts(events)
    report: Any = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError as e:
            reason = reason or f"report.json isn't valid JSON: {e}"
    elif reason is None:
        reason = "the agent finished without writing report.json"

    check = validate_report_in_workdir(workdir, rules, report) if report is not None else None
    fell_back = check is None or bool(check.errors)
    if fell_back:
        if check is not None and check.errors:
            reason = reason or f"report.json failed validation ({len(check.errors)} errors)"
            report_path.rename(workdir / "report.rejected.json")  # kept for review, never trusted
        report = fallback_report(analyse_workdir(workdir, rules), reason or "no valid report")
        check = validate_report_in_workdir(workdir, rules, report)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not check.errors:
        (workdir / "report.md").write_text(render(report, check.events), encoding="utf-8")
    turns = int(result_event.get("num_turns") or sum(1 for e in events if e.get("type") == "assistant"))
    transcript.write("final", valid=not check.errors, fell_back=fell_back, fallback_reason=reason if fell_back else None,
                     report_attempts=attempts, max_report_attempts=MAX_REPORT_ATTEMPTS, turns=turns, report=report,
                     errors=to_jsonable(check.errors))
    return AgentResult(report=report, valid=not check.errors, fell_back=fell_back,
                       fallback_reason=reason if fell_back else None, report_attempts=attempts, turns=turns,
                       transcript=transcript.path)
