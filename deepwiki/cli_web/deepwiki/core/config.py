"""User config (~/.config/cli-web-deepwiki/config.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field

from .session import config_dir


CONFIG_FILE = "config.json"


@dataclass
class Config:
    default_engine: str = "multihop_faster"   # "multihop_faster" | "deep_research"
    default_vault_root: str | None = None
    default_concurrency: int = 4
    rich_output: bool = True
    extras: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        path = config_dir() / CONFIG_FILE
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            default_engine=data.get("default_engine", "multihop_faster"),
            default_vault_root=data.get("default_vault_root"),
            default_concurrency=int(data.get("default_concurrency", 4)),
            rich_output=bool(data.get("rich_output", True)),
            extras=dict(data.get("extras") or {}),
        )

    def save(self) -> None:
        path = config_dir() / CONFIG_FILE
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def to_dict(self) -> dict:
        return asdict(self)
