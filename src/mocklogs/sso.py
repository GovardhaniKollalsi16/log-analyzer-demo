"""Mock SSO session (D21). Only the user runs `mocklogs sso login`; agents never do.

The session file holds a random MOCK marker standing in for a session token. It is
never printed, never written to --save-dir output, and tests assert it never leaks.
Session validity uses the real wall clock (not scenario time).
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

USER = "mock-user"
DEFAULT_TTL_MINUTES = 60


def home() -> Path:
    return Path(os.environ.get("MOCKLOGS_HOME", Path.home() / ".mocklogs"))


def _session_path() -> Path:
    return home() / "session.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def login(ttl_minutes: int = DEFAULT_TTL_MINUTES) -> datetime:
    expires = _now() + timedelta(minutes=ttl_minutes)
    home().mkdir(parents=True, exist_ok=True)
    path = _session_path()
    path.write_text(json.dumps({
        "user": USER,
        "expires_at": expires.isoformat(),
        "marker": f"MOCK-SESSION-{secrets.token_hex(12)}",
    }))
    path.chmod(0o600)
    return expires


def logout() -> None:
    try:
        _session_path().unlink()
    except FileNotFoundError:
        pass


def expires_at() -> Optional[datetime]:
    """Expiry of a valid session, or None if missing/expired/corrupt."""
    try:
        data = json.loads(_session_path().read_text())
        expires = datetime.fromisoformat(data["expires_at"])
    except (OSError, ValueError, KeyError):
        return None
    return expires if expires > _now() else None


def session_marker_for_tests() -> Optional[str]:
    try:
        return json.loads(_session_path().read_text())["marker"]
    except (OSError, ValueError, KeyError):
        return None
