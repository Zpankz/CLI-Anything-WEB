"""Shared fixtures for cli-web-deepwiki tests."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest


REPO = "agenticnotetaking/arscontexta"
INDEX_ID_PREFIX = "v1.9.9.5/PUBLIC/agenticnotetaking/arscontexta/"


@pytest.fixture
def test_repo() -> str:
    """The canonical E2E test repo."""
    return REPO


@pytest.fixture
def offline() -> bool:
    """Skip live calls if env says so."""
    return bool(os.environ.get("CLI_WEB_DEEPWIKI_OFFLINE"))


@pytest.fixture
def fixtures_dir() -> Path:
    """Local JSON fixtures captured during traffic recording."""
    here = Path(__file__).parent
    return here / "fixtures"


@pytest.fixture
def list_indexes_payload() -> dict:
    """Inline fixture for list_public_indexes (matches captured traffic)."""
    return {
        "indices": [
            {
                "id": INDEX_ID_PREFIX + "2acfd5cc",
                "repo_name": REPO,
                "last_modified": "2026-03-14T11:01:38.837154+00:00",
                "description": "Claude Code plugin that generates individualized knowledge systems from conversation.",
                "stargazers_count": 3143,
                "language": "Shell",
                "topics": ["claude-code", "knowledge-base", "second-brain"],
            }
        ],
        "needs_reindex": [],
        "pending_repos": [],
    }


@pytest.fixture
def query_done_payload() -> dict:
    """Inline fixture for GET /ada/query/{id} when state == done."""
    return {
        "title": "What are the kernel primitives?",
        "org_id": "PUBLIC",
        "queries": [
            {
                "message_id": "test-msg-1",
                "user_query": "What are the kernel primitives?",
                "use_knowledge": False,
                "engine_id": "multihop_faster",
                "model": None,
                "repo_names": [REPO],
                "repo_context_ids": [INDEX_ID_PREFIX + "2acfd5cc"],
                "repos": [{"name": REPO, "branch": None}],
                "response": [
                    {"type": "module_call_id", "data": {"module_call_id": "mc-1"}},
                    {"type": "chunk", "data": "The 15 kernel primitives are:\n\n"},
                    {"type": "chunk", "data": "1. **Atomic Notes** — one insight per file"},
                    {
                        "type": "reference",
                        "data": {
                            "file_path": "Repo agenticnotetaking/arscontexta: README.md",
                            "range_start": 200,
                            "range_end": 220,
                        },
                    },
                ],
                "error": None,
                "state": "done",
                "redis_stream": None,
                "module_call_id": "mc-1",
            }
        ],
    }


@pytest.fixture
def cli_invocation():
    """Returns the argv prefix to invoke the CLI in subprocess tests."""
    from cli_web.deepwiki.utils.helpers import _resolve_cli
    return _resolve_cli()
