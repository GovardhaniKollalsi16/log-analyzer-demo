"""Timestamps -> UTC, levels -> Level, stable event IDs, structured key extraction.

Assumptions (documented, tested):
- A timestamp without any zone (log4j `[2026-03-14 09:00:00,000]`) is taken as UTC.
- Business keys come ONLY from structured fields (`*_id` fields in JSON objects or
  DB statement columns), never from free text: Kafka's own "correlation id 8812"
  in producer logs is an internal request number, not an application ID.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from investigator.models import Level, Source

UTC = timezone.utc

_LEVELS = {
    "TRACE": Level.DEBUG, "DEBUG": Level.DEBUG,
    "INFO": Level.INFO, "LOG": Level.INFO, "NOTICE": Level.INFO,
    "WARN": Level.WARN, "WARNING": Level.WARN,
    "ERROR": Level.ERROR,
    "FATAL": Level.CRITICAL, "PANIC": Level.CRITICAL, "CRITICAL": Level.CRITICAL,
}

# In-app ID fields; everything else ending in _id is a business key (D25).
IN_APP_ID_FIELDS = {"correlation_id", "trace_id", "message_id", "request_id", "span_id"}

_FRACTION = re.compile(r"(\.\d+)")
_ZONE_NAMES = {"UTC": "+00:00", "GMT": "+00:00", "Z": "+00:00"}


def level(raw: str) -> Optional[Level]:
    return _LEVELS.get(raw.strip().upper())


def parse_ts(raw: str) -> Optional[datetime]:
    """Parse the timestamp shapes the tools emit. Returns aware UTC, or None if unparseable."""
    text = raw.strip()
    if not text:
        return None
    if text.isdigit() and len(text) >= 12:  # epoch milliseconds
        return datetime.fromtimestamp(int(text) / 1000, tz=UTC)
    text = text.replace(",", ".")  # log4j millis separator
    parts = text.split()
    if len(parts) == 3 and parts[2].upper() in _ZONE_NAMES:  # "2026-03-14 09:00:02.000 UTC"
        text = f"{parts[0]}T{parts[1]}{_ZONE_NAMES[parts[2].upper()]}"
    elif len(parts) == 2:  # "2026-03-14 09:00:00.000" (no zone -> UTC by assumption)
        text = f"{parts[0]}T{parts[1]}"
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Python 3.9's fromisoformat accepts at most 6 fractional digits (kubectl prints 9).
    m = _FRACTION.search(text)
    if m and len(m.group(1)) > 7:
        text = text.replace(m.group(1), m.group(1)[:7], 1)
    elif m and len(m.group(1)) not in (4, 7):  # pad .1 / .12 / .1234 / .12345 to 6 digits
        text = text.replace(m.group(1), (m.group(1) + "000000")[:7], 1)
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def event_id(source: Source, canonical_text: str) -> str:
    """Stable across runs and across commands that return the same record."""
    digest = hashlib.sha1(f"{source.value}\x1f{canonical_text}".encode("utf-8")).hexdigest()
    return f"ev-{digest[:12]}"


def business_keys(obj: Dict[str, Any]) -> Dict[str, str]:
    return {k: str(v) for k, v in obj.items()
            if k.endswith("_id") and k not in IN_APP_ID_FIELDS and isinstance(v, (str, int)) and str(v)}
