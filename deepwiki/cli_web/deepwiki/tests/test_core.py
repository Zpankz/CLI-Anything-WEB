"""Unit tests with mocked HTTP — no live network."""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

import httpx
import pytest

from cli_web.deepwiki.core.client import (
    DevinAdaClient,
    DeepwikiHTMLClient,
    ENGINE_IDS,
    MODE_ALIASES,
    _slugify_query,
    resolve_engine,
)
from cli_web.deepwiki.core.exceptions import (
    DeepwikiError,
    NotFoundError,
    raise_for_status,
)
from cli_web.deepwiki.core.models import Index, Page, Query, WikiTree, Reference
from cli_web.deepwiki.utils.helpers import (
    parse_repo,
    parse_repo_and_slug,
    safe_filename,
    _resolve_cli,
)


# ── helpers ──────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status: int, body, headers=None, cookies=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.cookies = cookies or {}
        if isinstance(body, (dict, list)):
            self.text = json.dumps(body)
            self._json = body
        else:
            self.text = body or ""
            self._json = None

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


# ── repo parsing ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("owner/repo", "owner/repo"),
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("https://deepwiki.com/owner/repo", "owner/repo"),
        ("https://deepwiki.com/owner/repo/", "owner/repo"),
        ("https://deepwiki.com/owner/repo/some-page", "owner/repo"),
        ("git@github.com:owner/repo.git", "owner/repo"),
    ],
)
def test_parse_repo(raw, expected):
    assert parse_repo(raw) == expected


def test_parse_repo_invalid():
    with pytest.raises(Exception):
        parse_repo("not-a-repo")


@pytest.mark.parametrize(
    "raw, repo, slug",
    [
        ("owner/repo", "owner/repo", None),
        ("owner/repo/page-1", "owner/repo", "page-1"),
        ("https://deepwiki.com/owner/repo/3.2-the-15-kernel-primitives",
         "owner/repo", "3.2-the-15-kernel-primitives"),
    ],
)
def test_parse_repo_and_slug(raw, repo, slug):
    r, s = parse_repo_and_slug(raw)
    assert r == repo
    assert s == slug


# ── slugify_query (Q&A query_id generation) ──────────────────────────────────


def test_slugify_query_basic():
    # 30 char slug — observed live: deepwiki uses [:30] truncation
    assert _slugify_query("What are the kernel primitives?") == "what-are-the-kernel-primitives"
    # When question contains numbers, those count too — matches captured live URL
    assert _slugify_query("What are the 15 kernel primitives?") == "what-are-the-15-kernel-primiti"


def test_slugify_query_truncation():
    s = _slugify_query("A" * 100)
    assert len(s) <= 30


def test_slugify_query_strip_trailing_dash():
    s = _slugify_query("hello world!?", max_len=15)
    assert not s.endswith("-")


# ── exceptions ────────────────────────────────────────────────────────────────


def test_raise_for_status_404():
    r = _FakeResponse(404, "missing")
    with pytest.raises(NotFoundError):
        raise_for_status(r)


def test_raise_for_status_2xx_no_raise():
    raise_for_status(_FakeResponse(200, {}))


def test_raise_for_status_429_retry_after():
    r = _FakeResponse(429, "rate", headers={"Retry-After": "30"})
    from cli_web.deepwiki.core.exceptions import RateLimitError
    with pytest.raises(RateLimitError) as exc_info:
        raise_for_status(r)
    assert exc_info.value.retry_after == 30


def test_exception_to_dict():
    err = DeepwikiError("boom")
    d = err.to_dict()
    assert d["error"] is True
    assert d["message"] == "boom"


# ── models ────────────────────────────────────────────────────────────────────


def test_index_from_dict(list_indexes_payload):
    idx = Index.from_dict(list_indexes_payload["indices"][0])
    assert idx.repo_name == "agenticnotetaking/arscontexta"
    assert idx.commit_sha == "2acfd5cc"
    assert idx.stargazers_count == 3143


def test_query_answer_markdown(query_done_payload):
    q = Query.from_dict(query_done_payload)
    assert q.state == "done"
    assert "kernel primitives" in q.answer_markdown
    assert "Atomic Notes" in q.answer_markdown


def test_query_references(query_done_payload):
    q = Query.from_dict(query_done_payload)
    refs = q.references
    assert len(refs) == 1
    assert refs[0].range_start == 200
    assert refs[0].range_end == 220


def test_reference_github_url():
    r = Reference(
        file_path="Repo agenticnotetaking/arscontexta: README.md",
        range_start=10,
        range_end=20,
    )
    url = r.github_url("agenticnotetaking/arscontexta", "abc12345")
    assert url is not None
    assert "github.com/agenticnotetaking/arscontexta/blob/abc12345/README.md" in url
    assert "#L10-L20" in url


def test_page_parent_slug():
    assert Page("o/r", "1-overview", "Overview").parent_slug is None
    assert Page("o/r", "3.1-foundation", "Foundation").parent_slug == "3"
    assert Page("o/r", "3.2.1-deep", "Deep").parent_slug == "3.2"


# ── DevinAdaClient (mocked) ───────────────────────────────────────────────────


def test_list_public_indexes_no_query(list_indexes_payload):
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, list_indexes_payload)
        client = DevinAdaClient()
        indices = client.list_public_indexes()
        client.close()
    assert len(indices) == 1
    assert isinstance(indices[0], Index)


def test_list_public_indexes_search(list_indexes_payload):
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, list_indexes_payload)
        client = DevinAdaClient()
        client.list_public_indexes(search_repo="rust")
        # Verify search_repo was passed as query param
        _, kwargs = m.call_args
        assert kwargs["params"] == {"search_repo": "rust"}
        client.close()


def test_get_index_match(list_indexes_payload):
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, list_indexes_payload)
        client = DevinAdaClient()
        idx = client.get_index("agenticnotetaking/arscontexta")
        assert idx is not None
        assert idx.repo_name == "agenticnotetaking/arscontexta"
        client.close()


def test_get_index_no_match():
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, {"indices": []})
        client = DevinAdaClient()
        idx = client.get_index("nonexistent/repo")
        assert idx is None
        client.close()


def test_submit_query_constructs_body(list_indexes_payload):
    """submit_query should look up the index ID and POST a well-formed body."""
    responses = [
        _FakeResponse(200, list_indexes_payload),    # list_public_indexes (lookup)
        _FakeResponse(200, {"status": "success"}),   # POST /ada/query
    ]
    with patch.object(httpx.Client, "request", side_effect=responses) as m:
        client = DevinAdaClient()
        qid = client.submit_query(
            "What are the kernel primitives?",
            "agenticnotetaking/arscontexta",
        )
        client.close()
    assert qid.startswith("what-are-the-kernel-primitives_")
    # Inspect POST call
    post_call = m.call_args_list[1]
    args, kwargs = post_call
    assert args[0] == "POST"
    body = kwargs["json"]
    assert body["repo_names"] == ["agenticnotetaking/arscontexta"]
    assert body["repo_context_ids"][0].endswith("/2acfd5cc")
    assert body["engine_id"] == "multihop_faster"


def test_submit_query_unknown_repo():
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, {"indices": []})
        client = DevinAdaClient()
        with pytest.raises(NotFoundError):
            client.submit_query("hi", "no/such")
        client.close()


def test_get_query(query_done_payload):
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, query_done_payload)
        client = DevinAdaClient()
        q = client.get_query("test-id")
        client.close()
    assert q.state == "done"
    assert q.title == "What are the kernel primitives?"


def test_stream_query_terminates_on_done(query_done_payload):
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(200, query_done_payload)
        client = DevinAdaClient()
        snapshots = list(
            client.stream_query("test", timeout=5, backoff_initial=0.01, backoff_max=0.01)
        )
        client.close()
    assert len(snapshots) == 1
    assert snapshots[0].state == "done"


def test_devin_client_uuid_cookie_capture(query_done_payload):
    """devin_client_uuid cookie set on response is captured in client.cookies."""
    with patch.object(httpx.Client, "request") as m:
        m.return_value = _FakeResponse(
            200,
            query_done_payload,
            cookies={"devin_client_uuid": "abc-xyz"},
        )
        client = DevinAdaClient()
        client.get_query("id")
    assert client.cookies["devin_client_uuid"] == "abc-xyz"
    client.close()


# ── DeepwikiHTMLClient (mocked) ──────────────────────────────────────────────


_OVERVIEW_HTML = """\
<html><head><title>agenticnotetaking/arscontexta | DeepWiki</title></head>
<body>
  <p>Last indexed: 14 March 2026 (
    <a href="https://github.com/agenticnotetaking/arscontexta/commits/2acfd5cc">2acfd5</a>)
  </p>
  <ul>
    <li><a href="/agenticnotetaking/arscontexta/1-overview">Overview</a></li>
    <li><a href="/agenticnotetaking/arscontexta/2-plugin-infrastructure">Plugin Infrastructure</a></li>
    <li><a href="/agenticnotetaking/arscontexta/3.2-the-15-kernel-primitives">The 15 Kernel Primitives</a></li>
  </ul>
</body></html>
"""


def test_fetch_repo_overview_extracts_metadata():
    with patch.object(httpx.Client, "get") as m:
        m.return_value = _FakeResponse(200, _OVERVIEW_HTML, headers={"content-type": "text/html"})
        client = DeepwikiHTMLClient()
        card = client.fetch_repo_overview("agenticnotetaking/arscontexta")
        client.close()
    assert card.last_indexed == "14 March 2026"
    assert card.indexed_commit and card.indexed_commit.startswith("2acfd5")
    assert "agenticnotetaking/arscontexta" in card.title


def test_fetch_wiki_tree_extracts_pages():
    with patch.object(httpx.Client, "get") as m:
        m.return_value = _FakeResponse(200, _OVERVIEW_HTML)
        client = DeepwikiHTMLClient()
        tree = client.fetch_wiki_tree("agenticnotetaking/arscontexta")
        client.close()
    assert isinstance(tree, WikiTree)
    assert "1-overview" in tree.slugs
    assert "3.2-the-15-kernel-primitives" in tree.slugs


# ── _resolve_cli ──────────────────────────────────────────────────────────────


def test_resolve_cli_dev_mode(monkeypatch):
    monkeypatch.delenv("CLI_WEB_FORCE_INSTALLED", raising=False)
    cmd = _resolve_cli()
    assert cmd[0] == sys.executable
    assert "cli_web.deepwiki" in cmd[-1] or cmd[-1].endswith("deepwiki")


# ── safe_filename: must match remark-deepwiki-wikilinks.js + MOC builder ─────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1-overview", "1-overview"),
        ("3.2-the-15-kernel-primitives", "3.2-the-15-kernel-primitives"),
        # Parens collapse to single dash (preserve numeric prefix)
        ("5.3-maps-of-content-(mocs)", "5.3-maps-of-content-mocs"),
        ("6.1-self-space-(agent-identity)", "6.1-self-space-agent-identity"),
        # Colons replaced (Windows-illegal)
        ("7.2-reduce:-knowledge-extraction", "7.2-reduce-knowledge-extraction"),
        ("7.3-reflect:-connection-discovery", "7.3-reflect-connection-discovery"),
        # Pipe / hash / brackets all collapse
        ("a|b#c[d]e", "a-b-c-d-e"),
        # Empty and edge cases
        ("", "page"),
        ("---", "page"),
        ("(())", "page"),
    ],
)
def test_safe_filename(raw, expected):
    """Must match the JS plugin's regex. CRITICAL — wikilinks would break."""
    assert safe_filename(raw) == expected


# ── engines / modes ───────────────────────────────────────────────────────────


def test_engine_ids_contains_known():
    """The official engine_id set discovered by probing the API."""
    assert "multihop_faster" in ENGINE_IDS
    assert "multihop" in ENGINE_IDS
    assert "codemap" in ENGINE_IDS
    assert "agent" in ENGINE_IDS
    assert "omni" in ENGINE_IDS
    assert "planning" in ENGINE_IDS


def test_resolve_engine_aliases():
    assert resolve_engine("fast") == "multihop_faster"
    assert resolve_engine("research") == "multihop"
    assert resolve_engine("codemap") == "codemap"
    assert resolve_engine("code-map") == "codemap"
    assert resolve_engine("deep") == "multihop"


def test_resolve_engine_passthrough():
    """Already-canonical engine_ids resolve to themselves."""
    for eid in ENGINE_IDS:
        assert resolve_engine(eid) == eid


def test_resolve_engine_default():
    assert resolve_engine(None) == "multihop_faster"
    assert resolve_engine("") == "multihop_faster"


def test_resolve_engine_invalid():
    from cli_web.deepwiki.core.exceptions import DeepwikiError
    with pytest.raises(DeepwikiError):
        resolve_engine("totally-invalid-mode")


# ── follow-up support ─────────────────────────────────────────────────────────


def test_follow_up_reuses_query_id(list_indexes_payload):
    """submit_query with a query_id should re-use it instead of generating new."""
    responses = [
        _FakeResponse(200, list_indexes_payload),
        _FakeResponse(200, {"status": "success"}),
    ]
    with patch.object(httpx.Client, "request", side_effect=responses) as m:
        client = DevinAdaClient()
        qid = client.follow_up(
            "existing_qid_xyz",
            "follow up question",
            "agenticnotetaking/arscontexta",
        )
        client.close()
    assert qid == "existing_qid_xyz"
    # POST body should carry the same query_id
    post_call = m.call_args_list[1]
    body = post_call.kwargs["json"]
    assert body["query_id"] == "existing_qid_xyz"


def test_query_thread_with_two_turns():
    """A 2-turn thread surfaces transcript, latest answer is from the tail."""
    payload = {
        "title": "thread",
        "org_id": "PUBLIC",
        "queries": [
            {
                "message_id": "m1",
                "user_query": "first",
                "engine_id": "multihop_faster",
                "model": None,
                "use_knowledge": False,
                "repo_names": [],
                "repo_context_ids": [],
                "repos": [],
                "response": [{"type": "chunk", "data": "First answer."}],
                "error": None,
                "state": "done",
                "redis_stream": None,
            },
            {
                "message_id": "m2",
                "user_query": "follow-up",
                "engine_id": "multihop",
                "model": None,
                "use_knowledge": False,
                "repo_names": [],
                "repo_context_ids": [],
                "repos": [],
                "response": [{"type": "chunk", "data": "Second answer."}],
                "error": None,
                "state": "done",
                "redis_stream": None,
            },
        ],
    }
    from cli_web.deepwiki.core.models import Query
    q = Query.from_dict(payload)
    assert q.turn_count == 2
    assert q.answer_markdown == "Second answer."
    assert q.primary.user_query == "first"
    assert q.latest.user_query == "follow-up"
    transcript = q.transcript
    assert len(transcript) == 2
    assert transcript[0]["answer"] == "First answer."
    assert transcript[1]["answer"] == "Second answer."


def test_thoughts_extraction():
    """omni-style responses with thoughts_start/_end blocks separate cleanly."""
    payload = {
        "title": "agent",
        "org_id": "PUBLIC",
        "queries": [{
            "message_id": "m",
            "user_query": "x",
            "engine_id": "omni",
            "model": None,
            "use_knowledge": False,
            "repo_names": [],
            "repo_context_ids": [],
            "repos": [],
            "response": [
                {"type": "thoughts_start", "data": None},
                {"type": "chunk", "data": "Let me think about this."},
                {"type": "thoughts_end", "data": None},
                {"type": "chunk", "data": "The answer is 42."},
            ],
            "error": None,
            "state": "done",
            "redis_stream": None,
        }],
    }
    from cli_web.deepwiki.core.models import Query
    q = Query.from_dict(payload)
    assert q.thoughts == ["Let me think about this."]
    # Answer excludes the thoughts content
    assert q.answer_markdown == "The answer is 42."


def test_tool_calls_extraction():
    payload = {
        "title": "x", "org_id": "PUBLIC",
        "queries": [{
            "message_id": "m", "user_query": "x", "engine_id": "omni",
            "model": None, "use_knowledge": False,
            "repo_names": [], "repo_context_ids": [], "repos": [],
            "response": [
                {"type": "tool_call_start", "data": {"name": "search_repo"}},
                {"type": "tool_call_complete", "data": {"name": "search_repo", "result": "ok"}},
            ],
            "error": None, "state": "done", "redis_stream": None,
        }],
    }
    from cli_web.deepwiki.core.models import Query
    q = Query.from_dict(payload)
    tc = q.tool_calls
    assert len(tc) == 2
    assert tc[0]["phase"] == "start"
    assert tc[1]["phase"] == "complete"
    assert tc[0]["data"]["name"] == "search_repo"
