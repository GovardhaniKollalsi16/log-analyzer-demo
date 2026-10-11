"""Route a saved output to its parser by command shape. Refusals become coverage gaps."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from investigator.adapters.base import RawOutput
from investigator.models import CoverageGap, GapReason, ParseIssue, ParseIssueKind, Source
from investigator.parsing import ParseResult, app_logs, config, db, kafka

# exit code -> gap reason (the tools' documented refusal codes, see the skills)
REFUSALS = {3: GapReason.AUTH_REQUIRED, 4: GapReason.ACCESS_DENIED, 5: GapReason.NOT_FOUND}

Parser = Callable[[RawOutput], ParseResult]


def command_shape(argv) -> Optional[Tuple[Source, Parser, str]]:
    """(component, parser, target) for a command line, or None if unknown."""
    args = argv[1:]  # drop the tool name
    def opt(name):
        for i, a in enumerate(args):
            if a == name and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(name + "="):
                return a.split("=", 1)[1]
        return None
    if args[:2] == ["kubectl", "logs"] and len(args) > 2:
        return Source.APP, app_logs.parse, args[2].split("/", 1)[-1]
    if args[:3] == ["kubectl", "get", "configmap"] and len(args) > 3:
        return Source.APP_CONFIG, config.parse, args[3]
    if args[:1] == ["kafka-consumer-groups"]:
        return Source.KAFKA, kafka.parse_groups, f"group:{opt('--group') or 'all'}"
    if args[:1] == ["kafka-get-offsets"]:
        return Source.KAFKA, kafka.parse_offsets, f"topic:{opt('--topic')}"
    if args[:1] == ["kafka-console-consumer"]:
        return Source.KAFKA, kafka.parse_messages, f"topic:{opt('--topic')}"
    if args[:2] == ["kafka", "logs"]:
        return Source.KAFKA, kafka.parse_logs, f"topic:{opt('--topic')}"
    if args[:2] == ["db", "logs"]:
        return Source.DB, db.parse, f"{opt('--host')}/{opt('--db')}"
    return None


def parse_output(out: RawOutput) -> ParseResult:
    shape = command_shape(out.argv)
    if shape is None:
        res = ParseResult()
        res.issues.append(ParseIssue(Source.APP, 0, ParseIssueKind.UNKNOWN_FORMAT, " ".join(out.argv),
                                     "unknown command shape"))
        return res
    component, parser, target = shape
    if out.exit_code in REFUSALS:
        detail = next((l for l in out.lines if l.strip() and not l.startswith("# MOCK")), "")
        res = ParseResult()
        res.gaps.append(CoverageGap(component, target, REFUSALS[out.exit_code], detail))
        return res
    if out.exit_code != 0:
        res = ParseResult()
        res.issues.append(ParseIssue(component, 0, ParseIssueKind.UNKNOWN_FORMAT, " ".join(out.argv),
                                     f"command failed with exit code {out.exit_code}"))
        return res
    return parser(out)

