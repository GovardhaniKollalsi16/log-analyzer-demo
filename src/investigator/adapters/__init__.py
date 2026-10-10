"""Where raw tool output comes from. Real integrations implement LogSource later."""

from __future__ import annotations

from investigator.adapters.base import LogSource, RawOutput
from investigator.adapters.files import FileSource

__all__ = ["LogSource", "RawOutput", "FileSource"]
