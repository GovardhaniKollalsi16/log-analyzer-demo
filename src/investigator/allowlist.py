"""The command allowlist, read from the component skills (single source of truth).

Each component skill carries one fenced JSON block:

    {"allowlist": [{"command": "kubectl logs", "flags": ["--context", ...], "valueless": ["--timestamps"]}]}

`investigator check` / `investigator run` merge all blocks. A command or flag that isn't listed
in a skill can't be run, so the skills the agent reads and the guard that enforces them can't
disagree.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set, Union

_BLOCK = re.compile(r"```json\n(\{\s*\"allowlist\".*?)\n```", re.S)


@dataclass
class Allowlist:
    flags: Dict[str, Set[str]] = field(default_factory=dict)  # command shape -> allowed flags
    valueless: Set[str] = field(default_factory=set)          # flags that take no value
    sources: Dict[str, str] = field(default_factory=dict)     # command shape -> skill it came from


def load_allowlist(skills_dir: Union[str, Path]) -> Allowlist:
    al = Allowlist()
    for skill in sorted(Path(skills_dir).glob("*/SKILL.md")):
        for block in _BLOCK.findall(skill.read_text(encoding="utf-8")):
            for entry in json.loads(block)["allowlist"]:
                shape = entry["command"]
                if shape in al.flags:
                    raise ValueError(f"{shape!r} is allowlisted twice ({al.sources[shape]} and {skill.parent.name})")
                al.flags[shape] = set(entry["flags"]) | {"--save-dir"}
                al.valueless |= set(entry.get("valueless", []))
                al.sources[shape] = skill.parent.name
    if not al.flags:
        raise ValueError(f"no allowlist blocks found under {skills_dir}")
    return al


def skills_dir_for(rules_path: Union[str, Path]) -> Path:
    """The coordinator skill lives in <skills>/incident-logs/SKILL.md; its grandparent is <skills>."""
    return Path(rules_path).resolve().parent.parent
