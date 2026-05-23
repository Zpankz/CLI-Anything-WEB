"""E2E tests against the live DeepWiki + Devin Ada API.

Test repo: https://deepwiki.com/agenticnotetaking/arscontexta

Skip with `pytest -m 'not e2e'` or `CLI_WEB_DEEPWIKI_OFFLINE=1`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cli_web.deepwiki.core.client import DeepwikiClient, DevinAdaClient, DeepwikiHTMLClient
from cli_web.deepwiki.utils.helpers import _resolve_cli


pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def skip_when_offline():
    if os.environ.get("CLI_WEB_DEEPWIKI_OFFLINE"):
        pytest.skip("CLI_WEB_DEEPWIKI_OFFLINE set — skipping E2E")


# ── Devin Ada API ─────────────────────────────────────────────────────────────


def test_list_public_indexes_live(test_repo):
    with DevinAdaClient() as client:
        idx = client.get_index(test_repo)
    assert idx is not None
    assert idx.repo_name == test_repo
    assert idx.id.startswith("v") and "/PUBLIC/" in idx.id
    assert idx.commit_sha and len(idx.commit_sha) >= 6


def test_search_returns_multiple_indices():
    with DevinAdaClient() as client:
        results = client.list_public_indexes(search_repo="rust")
    # Should match at least rust-lang/rust
    assert any("rust-lang/rust" == r.repo_name for r in results)


def test_ask_completes(test_repo):
    with DevinAdaClient() as client:
        q = client.ask(
            "What is this project about? Respond in 2-3 sentences.",
            test_repo,
            engine_id="multihop_faster",
        )
    assert q.state == "done"
    assert q.answer_markdown.strip(), "Expected non-empty answer"


# ── DeepWiki SSR HTML ─────────────────────────────────────────────────────────


def test_fetch_repo_overview_live(test_repo):
    with DeepwikiHTMLClient() as html:
        card = html.fetch_repo_overview(test_repo)
    assert card.repo == test_repo
    assert card.indexed_commit, "Expected an indexed commit"


def test_fetch_wiki_tree_live(test_repo):
    with DeepwikiHTMLClient() as html:
        tree = html.fetch_wiki_tree(test_repo)
    assert len(tree.pages) >= 10
    slugs = tree.slugs
    assert any(s.startswith("1-overview") for s in slugs)
    assert any("kernel-primitives" in s for s in slugs)


def test_fetch_page_live(test_repo):
    with DeepwikiHTMLClient() as html:
        page = html.fetch_page(test_repo, "1-overview")
    assert page.html and len(page.html) > 1000
    assert "Overview" in page.title


# ── End-to-end facade ─────────────────────────────────────────────────────────


def test_facade_works(test_repo):
    with DeepwikiClient() as cli:
        idx = cli.get_index(test_repo)
        card = cli.repo_overview(test_repo)
        tree = cli.wiki_tree(test_repo)
    assert idx is not None
    assert card.repo == test_repo
    assert len(tree.pages) >= 10


# ── Subprocess (the public binary) ───────────────────────────────────────────


def _run_cli(*args, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = _resolve_cli() + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "CLI_WEB_DEEPWIKI_OFFLINE": ""},
    )


def test_cli_help():
    r = _run_cli("--help")
    assert r.returncode == 0
    out = r.stdout.lower()
    assert "deepwiki" in out
    # Verify all primary commands are listed
    for c in ("search", "repo", "wiki", "page", "ask", "vault"):
        assert c in out, f"--help missing {c}"


def test_cli_version():
    r = _run_cli("--version")
    assert r.returncode == 0
    assert "0.1.0" in r.stdout


def test_cli_search_json():
    r = _run_cli("search", "rust", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert isinstance(data, list)
    assert any("rust" in (d.get("repo_name") or "").lower() for d in data)


def test_cli_repo_json(test_repo):
    r = _run_cli("repo", test_repo, "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    # Our repo command returns {index, overview} or single object
    assert "index" in data or "repo_name" in data or "repo" in data


def test_cli_wiki_json(test_repo):
    r = _run_cli("wiki", test_repo, "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data.get("count", 0) >= 10
    assert isinstance(data.get("pages"), list)


# ── Vault generation (requires unified sidecar) ──────────────────────────────


@pytest.mark.unified
def test_vault_generation(tmp_path, test_repo):
    """Generate vault for arscontexta. Smoke test only — first 3 pages."""
    out = tmp_path / "vault"
    r = _run_cli(
        "vault", test_repo,
        "--output", str(out),
        "--limit", "3",
        "--mocs", "--canvas", "--frontmatter",
        "--json",
        timeout=300,
    )
    assert r.returncode == 0, r.stderr
    # At least one .md generated
    mds = list(out.glob("*.md"))
    assert mds, "No markdown files written"
    # Frontmatter present in at least one
    has_frontmatter = any(p.read_text().lstrip().startswith("---") for p in mds)
    assert has_frontmatter, "Expected YAML frontmatter in vault pages"


@pytest.mark.unified
def test_extract_command(tmp_path, test_repo):
    """`extract` should defuddle a wiki page into clean Markdown."""
    url = f"https://deepwiki.com/{test_repo}/1-overview"
    r = _run_cli("extract", url, "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data.get("markdown"), "Expected non-empty markdown"
