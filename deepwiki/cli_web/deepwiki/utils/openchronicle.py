"""Optional integration with OpenChronicle (the user's local memory layer).

Each significant CLI invocation can append a summary to OpenChronicle so
future agents can recover what the user was researching.

If openchronicle is not configured (or its CLI/API isn't reachable), every
function here is a silent no-op — never raises, never blocks the CLI.

Activation: set CLI_WEB_DEEPWIKI_CHRONICLE=1 (or =/path/to/storage).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENV_VAR = "CLI_WEB_DEEPWIKI_CHRONICLE"


def is_enabled() -> bool:
    return bool(os.environ.get(ENV_VAR))


def _storage_path() -> Path | None:
    """Where to append events. The env var may be a directory or '1'."""
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return None
    if raw in ("1", "true", "yes"):
        from ..core.session import config_dir
        return config_dir() / "chronicle.ndjson"
    p = Path(raw).expanduser()
    if p.is_dir():
        return p / "deepwiki-chronicle.ndjson"
    return p


def _record_local(event: dict) -> None:
    """Persist event to a local ndjson log."""
    path = _storage_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _record_via_cli(event: dict) -> bool:
    """If the openchronicle CLI is on PATH, send to its capture endpoint."""
    chr_cli = shutil.which("openchronicle")
    if not chr_cli:
        return False
    try:
        proc = subprocess.run(
            [chr_cli, "capture", "--source", "cli-web-deepwiki", "--json", "-"],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            timeout=3,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def record(kind: str, **fields: Any) -> None:
    """Record one event. Best-effort: never raises.

    Sample kinds: 'search', 'repo', 'wiki', 'page', 'ask', 'vault'.
    """
    if not is_enabled():
        return
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "cli-web-deepwiki",
        "kind": kind,
        **{k: v for k, v in fields.items() if v is not None},
    }
    if not _record_via_cli(event):
        _record_local(event)


# ── decorators ────────────────────────────────────────────────────────────────


def chronicle(kind: str):
    """Decorator: record successful invocations to OpenChronicle.

    Captures the function's args + a coarse "ok"/"error" outcome.
    """
    def deco(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                record(
                    kind,
                    outcome="ok",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    args={k: _safe(v) for k, v in kwargs.items()},
                )
                return result
            except Exception as exc:
                record(
                    kind,
                    outcome="error",
                    error=type(exc).__name__,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                raise
        return wrapper
    return deco


def _safe(value: Any) -> Any:
    """Trim large strings, redact obvious secrets."""
    if isinstance(value, str):
        if len(value) > 500:
            return value[:500] + "…"
        if value.startswith(("sk-", "github_pat_", "ghp_")):
            return "[redacted]"
    return value
