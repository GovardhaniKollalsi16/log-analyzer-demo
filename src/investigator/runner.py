"""The only way the agent fetches: check the command, then run it without a shell, and log the attempt.

Used by `investigator run` (CLI / Claude Code subagent) and by the Python agent loop's `run` tool,
so both paths enforce exactly the same guardrails.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Union

from investigator.allowlist import load_allowlist, skills_dir_for
from investigator.correlation_keys import load_rules
from investigator.guard import check

ACTIONS_FILE = "actions.jsonl"
TIMEOUT_S = 120


@dataclass
class RunResult:
    allowed: bool
    exit_code: int                      # the command's own code, or 1 if denied
    stdout: str = ""
    stderr: str = ""
    denials: List[Dict[str, str]] = field(default_factory=list)


def run_checked(workdir: Union[str, Path], rules_path: Union[str, Path], argv: List[str], reason: str) -> RunResult:
    from investigator.pipeline import prepare  # local import: pipeline imports a lot
    workdir = Path(workdir)
    p = prepare(workdir, load_rules(rules_path))
    verdict = check(argv, p.incident, p.topology, str(workdir), load_allowlist(skills_dir_for(rules_path)))
    record = {"ts": datetime.now(timezone.utc).isoformat(), "argv": argv, "reason": reason,
              "allowed": verdict.allowed, "denials": verdict.reasons}
    if verdict.allowed:
        proc = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=TIMEOUT_S)
        result = RunResult(True, proc.returncode, proc.stdout, proc.stderr)
        record["exit_code"] = proc.returncode
    else:
        result = RunResult(False, 1, denials=verdict.reasons)
    with open(workdir / ACTIONS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return result
