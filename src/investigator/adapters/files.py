"""Reads what `--save-dir <workdir>` wrote: raw/NNN-*.txt + NNN-*.meta.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Union

from investigator.adapters.base import RawOutput


class FileSource:
    def __init__(self, workdir: Union[str, Path]):
        self.raw_dir = Path(workdir) / "raw"

    def outputs(self) -> Iterator[RawOutput]:
        if not self.raw_dir.is_dir():
            return
        for txt in sorted(self.raw_dir.glob("*.txt")):
            meta_path = txt.with_suffix(".meta.json")
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                argv, exit_code = list(meta["argv"]), int(meta["exit_code"])
            except (OSError, ValueError, KeyError):
                continue  # an output without readable provenance can't be used as evidence
            text = txt.read_text(encoding="utf-8", errors="replace")
            yield RawOutput(name=txt.stem, argv=argv, exit_code=exit_code, lines=text.splitlines())
