"""Shared helpers for cli-web-deepwiki commands."""
from __future__ import annotations

import functools
import io
import json as _json
import os
import shutil
import sys
from contextlib import contextmanager
from typing import Callable

import click

from ..core.exceptions import DeepwikiError


# ── repo/slug parsing ─────────────────────────────────────────────────────────


def parse_repo(arg: str) -> str:
    """Accept any of:
      - owner/repo
      - https://github.com/owner/repo[/...]
      - https://deepwiki.com/owner/repo[/...]
    Returns canonical 'owner/repo'.
    """
    s = arg.strip()
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "https://deepwiki.com/",
        "http://deepwiki.com/",
        "git@github.com:",
    ):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = s.split("/")
    if len(parts) < 2:
        raise click.BadParameter(f"Expected owner/repo, got: {arg!r}")
    return f"{parts[0]}/{parts[1]}"


def safe_filename(slug: str) -> str:
    """Map a DeepWiki slug to a filename / wikilink-safe stem.

    Must produce the SAME output as `remark-deepwiki-wikilinks.js` so the
    filename written to disk matches the wikilink target rendered inside
    pages and the MOC.

    Rules (mirroring the JS plugin):
      - Strip `[]()|#`               (Obsidian-illegal in wikilinks)
      - Strip `:*?"<>\\/`            (filesystem-illegal on Windows)
      - Collapse runs of `-` and trim trailing
    Result: `5.3-maps-of-content-(mocs)` → `5.3-maps-of-content-mocs`,
            `7.2-reduce:-knowledge-extraction` → `7.2-reduce-knowledge-extraction`
    """
    import re as _re
    if not isinstance(slug, str):
        return "page"
    cleaned = _re.sub(r"[\[\]()|#:*?\"<>\\/]", "-", slug)
    cleaned = _re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "page"


def parse_repo_and_slug(arg: str) -> tuple[str, str | None]:
    """Accept owner/repo[/slug] or full DeepWiki URL → (repo, slug|None)."""
    s = arg.strip()
    for prefix in ("https://deepwiki.com/", "http://deepwiki.com/"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.rstrip("/")
    parts = s.split("/", 2)
    if len(parts) < 2:
        raise click.BadParameter(f"Expected owner/repo[/slug], got: {arg!r}")
    repo = f"{parts[0]}/{parts[1]}"
    slug = parts[2] if len(parts) > 2 else None
    return repo, slug


# ── UTF-8 enforcement ─────────────────────────────────────────────────────────


def ensure_utf8() -> None:
    """Force UTF-8 on stdout/stderr (Windows-safe, idempotent)."""
    for stream_attr in ("stdout", "stderr"):
        s = getattr(sys, stream_attr)
        enc = getattr(s, "encoding", "") or ""
        if enc.lower() not in ("utf-8", "utf8"):
            if hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace")
            else:
                wrapped = io.TextIOWrapper(s.buffer, encoding="utf-8", errors="replace")
                setattr(sys, stream_attr, wrapped)


# ── error handling ────────────────────────────────────────────────────────────


@contextmanager
def handle_errors(json_mode: bool = False):
    """Catch domain exceptions and emit structured output or friendly errors.

    Usage:
        with handle_errors(json_mode=ctx.obj.get("json")):
            do_something()
    """
    try:
        yield
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (click.exceptions.Exit, click.UsageError, click.BadParameter):
        raise
    except DeepwikiError as exc:
        if json_mode:
            click.echo(_json.dumps(exc.to_dict(), ensure_ascii=False))
        else:
            click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        raise SystemExit(_exit_code_for(exc))
    except Exception as exc:  # pragma: no cover — last-line safety net
        if json_mode:
            click.echo(_json.dumps({
                "error": True,
                "code": "INTERNAL_ERROR",
                "message": str(exc),
                "type": type(exc).__name__,
            }, ensure_ascii=False))
        else:
            click.echo(
                click.style(
                    f"Internal error: {type(exc).__name__}: {exc}",
                    fg="red",
                ),
                err=True,
            )
        raise SystemExit(99)


def with_errors(func: Callable) -> Callable:
    """Decorator equivalent of `with handle_errors(...)` for click commands."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context(silent=True)
        json_mode = bool(ctx and ctx.obj and ctx.obj.get("json"))
        with handle_errors(json_mode=json_mode):
            return func(*args, **kwargs)
    return wrapper


def _exit_code_for(exc: DeepwikiError) -> int:
    name = type(exc).__name__
    return {
        "AuthError": 1,
        "ServerError": 2,
        "NetworkError": 3,
        "RateLimitError": 4,
        "NotFoundError": 5,
    }.get(name, 9)


# ── output helpers ────────────────────────────────────────────────────────────


def emit(data, *, json_mode: bool, table_renderer=None) -> None:
    """Emit structured data: JSON in --json mode, otherwise via callback."""
    if json_mode:
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        elif isinstance(data, list) and data and hasattr(data[0], "to_dict"):
            data = [x.to_dict() for x in data]
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif table_renderer is not None:
        table_renderer(data)
    else:
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2, default=str))


def emit_json(data) -> None:
    """Force-emit JSON regardless of mode."""
    if hasattr(data, "to_dict"):
        data = data.to_dict()
    elif isinstance(data, list) and data and hasattr(data[0], "to_dict"):
        data = [x.to_dict() for x in data]
    click.echo(_json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── _resolve_cli (subprocess test convention) ─────────────────────────────────


def _resolve_cli() -> list[str]:
    """Return the CLI invocation list for subprocess tests.

    Resolution order:
      1. CLI_WEB_FORCE_INSTALLED=1 → use the installed entry point (prefer `dw`,
         fall back to `cli-web-deepwiki`).
      2. Default → `python -m cli_web.deepwiki` for in-tree development.
    """
    if os.environ.get("CLI_WEB_FORCE_INSTALLED") == "1":
        for name in ("dw", "cli-web-deepwiki"):
            path = shutil.which(name)
            if path:
                return [path]
        raise RuntimeError(
            "Neither `dw` nor `cli-web-deepwiki` on PATH; run `pip install -e .`"
        )
    return [sys.executable, "-m", "cli_web.deepwiki"]
