"""A stand-in for `claude -p --agent incident-investigator` (tests only; never touches an account).

It behaves like the subagent at the process boundary: reads the first message on stdin, sends every
Bash command through the real PreToolUse hook (.claude/hooks/allowlist_guard.py, from the cwd) and
runs it only if the hook allows, writes the report file, and prints stream-json events.
FAKE_CLAUDE_MODE picks the behaviour; FAKE_CLAUDE_RECORD (a path) receives its argv and env facts.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

HOOK = Path(".claude/hooks/allowlist_guard.py")
EVENTS = []
N = [0]


def emit(event):
    EVENTS.append(event)
    print(json.dumps(event), flush=True)


def bash(command):
    N[0] += 1
    tid = f"toolu_{N[0]}"
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                        "input": {"command": command}}]}})
    hook = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": os.getcwd()}),
        capture_output=True, text=True)
    if hook.returncode == 2:
        emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                       "is_error": True, "content": hook.stderr}]}})
        return None, hook.stderr
    r = subprocess.run(shlex.split(command), capture_output=True, text=True)
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                   "content": (r.stdout + r.stderr)[-2000:]}]}})
    return r, None


def write(path, report):
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_w", "name": "Write",
                                                        "input": {"file_path": str(path)}}]}})
    Path(path).write_text(json.dumps(report, indent=2))


def collect(workdir):
    for _ in range(10):
        r, _ = bash(f"investigator plan --workdir {workdir}")
        plan = json.loads(r.stdout)
        if plan["done"]:
            return
        for step in plan["steps"]:
            bash(shlex.join(["investigator", "run", "--workdir", str(workdir), "--reason", step["reason"], "--",
                             *step["argv"]]))


def report_for(workdir, mode):
    from investigator.agent.fake import ScriptedInvestigator
    from investigator.agent.narration import summarize
    from investigator.correlation_keys import load_rules
    from investigator.pipeline import analyse_workdir
    r, _ = bash(f"investigator correlate --workdir {workdir}")  # what the model would read
    fake = ScriptedInvestigator(bogus_first=(mode == "invalid"), never_valid=(mode == "invalid"))
    fake.summary = summarize(analyse_workdir(workdir, load_rules(Path(".claude/skills/incident-logs/SKILL.md"))))
    cause = fake._choose_cause() if mode != "unknown" else None
    if cause:
        r, _ = bash(f"investigator score --workdir {workdir} --cause {cause}")
        fake.scored = json.loads(r.stdout)
    return fake._report()


def main():
    prompt = sys.stdin.read()
    mode = os.environ.get("FAKE_CLAUDE_MODE", "lead")
    record = os.environ.get("FAKE_CLAUDE_RECORD")
    if record:
        Path(record).write_text(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt,
                                            "secret_env": [k for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
                                                           if k in os.environ]}))
    emit({"type": "system", "subtype": "init", "agent": "incident-investigator"})
    if mode == "crash":
        print("boom", file=sys.stderr)
        return 1
    workdir = Path(prompt.splitlines()[0].split("workdir: ", 1)[1])
    if mode == "forbidden":
        bash("cat /etc/passwd")
        bash(f"investigator plan --workdir {workdir} && rm -rf {workdir}")
        bash("mocklogs sso login")
    collect(workdir)
    if mode == "no_report":
        emit({"type": "result", "subtype": "success", "num_turns": len(EVENTS), "result": "I'm done."})
        return 0
    report_path = workdir / "report.json"
    for _ in range(3):
        write(report_path, report_for(workdir, mode))
        r, _ = bash(f"investigator validate --workdir {workdir} --report {report_path}")
        if r.returncode == 0:
            break
    emit({"type": "result", "subtype": "success", "num_turns": sum(e["type"] == "assistant" for e in EVENTS),
          "result": f"REPORT: {report_path}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
