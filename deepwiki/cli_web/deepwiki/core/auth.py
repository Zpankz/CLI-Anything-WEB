"""Auth — DeepWiki / Devin Ada API requires no login.

The Devin Ada API issues a `devin_client_uuid` cookie on first POST. We persist
this cookie across CLI invocations for usage attribution but it is not required.

This module exposes:
  - `load_cookies()` → dict, with env-var override CLI_WEB_DEEPWIKI_AUTH_JSON
  - `save_cookies(cookies)` → None
  - `clear()` → None
"""
from __future__ import annotations

import json
import os

from .session import Session, config_dir


AUTH_FILE = "cookies.json"
ENV_VAR = "CLI_WEB_DEEPWIKI_AUTH_JSON"


def load_cookies() -> dict:
    """Return persisted cookies. Honors env var override for CI."""
    raw = os.environ.get(ENV_VAR)
    if raw:
        try:
            return _normalize(json.loads(raw))
        except json.JSONDecodeError:
            return {}
    path = config_dir() / AUTH_FILE
    if not path.is_file():
        return {}
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cookies(cookies: dict) -> None:
    if not cookies:
        return
    path = config_dir() / AUTH_FILE
    path.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except (OSError, PermissionError):
        pass


def clear() -> None:
    path = config_dir() / AUTH_FILE
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    Session.load().reset()


def status() -> dict:
    """Used by `auth status` command."""
    cookies = load_cookies()
    return {
        "authenticated": bool(cookies),
        "cookie_count": len(cookies),
        "config_dir": str(config_dir()),
        "env_override": ENV_VAR in os.environ,
    }


def _normalize(data) -> dict:
    """Accept both `{name: value}` dict form and Playwright-style list.

    Per HARNESS.md auth-strategies #cookie-domain-priority, when the same
    cookie name appears with multiple domains, prefer `.devin.ai` over any
    regional duplicate.
    """
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    if isinstance(data, list):
        out: dict[str, tuple[str, str]] = {}  # name -> (value, domain)
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            value = entry.get("value")
            domain = entry.get("domain") or ""
            if not name or value is None:
                continue
            existing = out.get(name)
            if existing and not _is_higher_priority(domain, existing[1]):
                continue
            out[name] = (str(value), domain)
        return {k: v[0] for k, v in out.items()}
    return {}


def _is_higher_priority(domain_a: str, domain_b: str) -> bool:
    """Prefer `.devin.ai` exact-suffix domains."""
    a = (domain_a or "").lower()
    b = (domain_b or "").lower()
    if a == ".devin.ai" and b != ".devin.ai":
        return True
    if a == "devin.ai" and not b.startswith(".devin.ai"):
        return True
    return False
