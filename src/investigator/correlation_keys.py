"""Which business key correlates across services (D25).

The rules are user-maintained in the coordinator skill (`incident-logs` §3) as a
fenced JSON block; this module only reads and applies them. Nothing here knows any
app, topic or scenario name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

_BLOCK = re.compile(r"```json\n(\{\s*\"correlation_keys\".*?)\n```", re.S)


@dataclass(frozen=True)
class KeyRule:
    source_class_prefix: str
    key: str
    stored_as: Dict[str, str]


def load_rules(skill_md: Union[str, Path]) -> List[KeyRule]:
    text = Path(skill_md).read_text(encoding="utf-8")
    m = _BLOCK.search(text)
    if not m:
        raise ValueError(f"no correlation_keys JSON block in {skill_md}")
    return [KeyRule(r["source_class_prefix"], r["key"], dict(r["stored_as"]))
            for r in json.loads(m.group(1))["correlation_keys"]]


def source_class(logger: Optional[str]) -> str:
    return (logger or "").rsplit(".", 1)[-1]


def choose_business_key(logger: Optional[str], keys: Dict[str, str], rules: List[KeyRule]) -> Optional[str]:
    """First rule whose prefix matches the seed's source class AND whose key the seed carries."""
    cls = source_class(logger)
    for rule in rules:
        if cls.startswith(rule.source_class_prefix):
            return rule.key if keys.get(rule.key) else None
    return None
