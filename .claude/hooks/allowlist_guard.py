#!/usr/bin/env python3
"""PreToolUse hook for the incident-investigator subagent (D7, D32).

Bash may run ONLY `investigator <subcommand> ...`, as one plain command: no shell operators,
redirections, substitutions or variables. Exit 0 = allow, exit 2 = block (the reason goes to
stderr, which Claude Code shows to the model). Everything an allowed command does is then
checked again by `investigator run` (allowlist, incident/config provenance).
"""

import json
import shlex
import sys

ALLOWED_SUBCOMMANDS = {"init", "plan", "run", "correlate", "check", "score", "validate", "render"}
FORBIDDEN = ["&&", "||", ";", "|", "&", ">", "<", "`", "$(", "${", "\n"]


def decide(command: str):
    """Return None to allow, or a reason string to block."""
    stripped = command.strip()
    # Operators are matched anywhere in the raw text, even inside quotes: telling quoted text from
    # real operators reliably isn't worth the risk here. (The report JSON is written with the Write
    # tool, never passed inline, so no legitimate command needs these characters.)
    for op in FORBIDDEN:
        if op in stripped:
            return f"shell operator {op!r} isn't allowed; run one plain `investigator` command"
    try:
        words = shlex.split(stripped)
    except ValueError as e:
        return f"can't parse the command: {e}"
    if not words or words[0] != "investigator":
        return "only `investigator ...` commands may run (fetch with `investigator run ... -- mocklogs ...`)"
    if len(words) < 2 or words[1] not in ALLOWED_SUBCOMMANDS:
        return f"`investigator {words[1] if len(words) > 1 else ''}` isn't allowed here"
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        print("hook: unreadable input", file=sys.stderr)
        return 2
    if event.get("tool_name") != "Bash":
        return 0
    reason = decide(str((event.get("tool_input") or {}).get("command", "")))
    if reason:
        print(f"Blocked by the incident-investigator guard: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
