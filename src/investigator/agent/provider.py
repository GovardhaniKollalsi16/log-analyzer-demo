"""The LLM behind the Python agent loop, behind one small interface. Only scripted fakes implement it; the real
model runs through Claude Code instead (agent/claude_code.py, D32)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore[assignment,misc]


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class AssistantTurn:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]


class LLMProvider(Protocol):
    """`messages` are dicts: {"role": "system"|"user"|"assistant"|"tool", ...}. Tool results come back
    as {"role": "tool", "tool_call_id", "name", "content": <JSON string>}."""

    def respond(self, messages: List[Dict[str, Any]], tools: List[ToolSpec]) -> AssistantTurn:
        ...
