"""Session and persistent context for cli-web-deepwiki.

Stores the `devin_client_uuid` cookie (issued on first POST /ada/query) and the
"current repo" context for `use <owner>/<repo>` workflows. Lives at
~/.config/cli-web-deepwiki/.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def config_dir() -> Path:
    """Return the persistent config directory (creates if missing)."""
    base = os.environ.get("CLI_WEB_DEEPWIKI_HOME")
    if base:
        d = Path(base).expanduser()
    else:
        d = Path.home() / ".config" / "cli-web-deepwiki"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except (OSError, PermissionError):
        pass
    return d


@dataclass
class Session:
    """Stateful session with cookies and current-repo context."""
    cookies: dict[str, str] = field(default_factory=dict)
    current_repo: str | None = None
    last_query_id: str | None = None

    @classmethod
    def load(cls) -> "Session":
        path = config_dir() / "session.json"
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            cookies=dict(data.get("cookies") or {}),
            current_repo=data.get("current_repo"),
            last_query_id=data.get("last_query_id"),
        )

    def save(self) -> None:
        path = config_dir() / "session.json"
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except (OSError, PermissionError):
            pass

    def use(self, repo: str) -> None:
        self.current_repo = repo
        self.save()

    def reset(self) -> None:
        self.cookies = {}
        self.current_repo = None
        self.last_query_id = None
        path = config_dir() / "session.json"
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass

    def to_dict(self) -> dict:
        return {
            "current_repo": self.current_repo,
            "last_query_id": self.last_query_id,
            "has_cookies": bool(self.cookies),
            "config_dir": str(config_dir()),
        }
