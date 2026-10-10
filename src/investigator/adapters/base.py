from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List

try:  # Protocol is in typing from 3.8
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore[assignment,misc]


@dataclass(frozen=True)
class RawOutput:
    """One saved command output: exactly what the tool printed, plus how it was produced."""

    name: str          # e.g. "003-kubectl-get-configmap-..." (stable ordering key)
    argv: List[str]    # full command line, starting with the tool name
    exit_code: int
    lines: List[str]   # every printed line, banner included


class LogSource(Protocol):
    def outputs(self) -> Iterator[RawOutput]:
        ...
