"""HTTP client for cli-web-deepwiki.

Two backends:
  DevinAdaClient — api.devin.ai/ada/* (search + Q&A)
  DeepwikiHTMLClient — deepwiki.com/{owner}/{repo}[/{slug}] (SSR HTML)

Both share base_url-less httpx clients with browser-mimicking headers; CORS
on the Ada API requires Origin=https://deepwiki.com.

HTTP status code mapping (delegated to core.exceptions.raise_for_status):
  - 401, 403  → AuthError      (with retry_on_auth flag — see _request below)
  - 404       → NotFoundError
  - 429       → RateLimitError (honors Retry-After header)
  - 5xx       → ServerError

Auth retry policy: when the Devin Ada API returns 401/403 (rare since the API
accepts anonymous calls), _request() retries once after refreshing the cookie
jar. retry_on_auth=False on the second attempt to avoid infinite loops.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Iterable, Iterator
from urllib.parse import quote

import httpx

from .exceptions import (
    DeepwikiError,
    AuthError,
    NetworkError,
    RateLimitError,
    raise_for_status,
)
from .models import Index, Page, Query, RepoCard, WikiTree


# ── Shared HTTP defaults ──────────────────────────────────────────────────────

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 "
    "cli-web-deepwiki/0.1.0"
)
_DEEPWIKI_HEADERS = {
    "Origin": "https://deepwiki.com",
    "Referer": "https://deepwiki.com/",
    "User-Agent": _BROWSER_UA,
    "Accept-Language": "en-US,en;q=0.9",
}


def _slugify_query(text: str, max_len: int = 30) -> str:
    """Turn a question into the slug DeepWiki uses for query_id."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "q"


# Valid engine_id values accepted by /ada/query.
# Discovered via probe — server validates against this exact enum.
ENGINE_IDS = (
    "agent",                # specialized agent runs
    "codemap",              # CODE MAP queries — structural/symbol mapping
    "multihop",             # standard thorough research
    "multihop_faster",      # FAST mode (default in UI)
    "multihop_mcp",         # MCP-routed multihop
    "omni",                 # omni
    "omni_quick_preview",   # omni quick
    "planning",             # planning mode
    "spaces_handoff",       # internal
)

# CLI-friendly aliases → real engine_id
MODE_ALIASES: dict[str, str] = {
    "fast": "multihop_faster",
    "faster": "multihop_faster",
    "default": "multihop_faster",
    "research": "multihop",
    "deep": "multihop",
    "deep-research": "multihop",
    "thorough": "multihop",
    "codemap": "codemap",
    "code-map": "codemap",
    "code_map": "codemap",
    "agent": "agent",
    "omni": "omni",
    "omni-quick": "omni_quick_preview",
    "planning": "planning",
    "mcp": "multihop_mcp",
}


def resolve_engine(mode: str | None) -> str:
    """Map a friendly mode name to a valid engine_id; defaults to fast."""
    if not mode:
        return "multihop_faster"
    m = mode.strip().lower()
    if m in ENGINE_IDS:
        return m
    if m in MODE_ALIASES:
        return MODE_ALIASES[m]
    raise DeepwikiError(
        f"Unknown mode {mode!r}. Valid: "
        f"{', '.join(sorted(set(MODE_ALIASES) | set(ENGINE_IDS)))}"
    )


def _derive_title_from_html(html: str) -> str | None:
    """Pick the first reasonable <h1> from the rendered article body."""
    # Skip sidebar TOC links — those are <a> not <h1>
    for m in re.finditer(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL):
        raw = m.group(1)
        # Strip nested HTML tags (Edit/Copy buttons embedded inside h1)
        text = re.sub(r"<[^>]+>", "", raw).strip()
        # Strip the "Copy link to header" trailer the renderer adds
        text = re.sub(r"\s*Copy link to header\s*$", "", text, flags=re.IGNORECASE)
        if text:
            return text
    return None


def _slug_to_title(slug: str) -> str:
    """Fallback: turn `3.2-the-15-kernel-primitives` → `The 15 Kernel Primitives`."""
    body = re.sub(r"^\d+(?:\.\d+)*-?", "", slug)
    parts = [p for p in re.split(r"[-_]+", body) if p]
    return " ".join(p.capitalize() if not p.isdigit() else p for p in parts) or slug


# ── Devin Ada API ─────────────────────────────────────────────────────────────


class DevinAdaClient:
    """Client for api.devin.ai/ada/* — Devin's underlying search + Q&A API."""

    BASE_URL = "https://api.devin.ai"

    def __init__(
        self,
        cookies: dict | None = None,
        timeout: float = 30.0,
    ):
        self._cookies = cookies or {}
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=timeout, pool=timeout),
            headers={"Content-Type": "application/json", **_DEEPWIKI_HEADERS},
            follow_redirects=True,
        )

    # ── search / discovery ────────────────────────────────────────────────────

    def list_public_indexes(self, search_repo: str | None = None) -> list[Index]:
        """GET /ada/list_public_indexes — search/list indexed public repos."""
        params: dict = {}
        if search_repo:
            params["search_repo"] = search_repo
        resp = self._get("/ada/list_public_indexes", params=params)
        payload = resp.json()
        return [Index.from_dict(d) for d in payload.get("indices", [])]

    def get_index(self, repo: str) -> Index | None:
        """Look up a single repo by `owner/repo` (uses search filter)."""
        owner, _, name = repo.partition("/")
        if not name:
            raise DeepwikiError(f"Expected owner/repo format, got: {repo!r}")
        for idx in self.list_public_indexes(search_repo=name):
            if idx.repo_name.lower() == repo.lower():
                return idx
        return None

    # ── Q&A ───────────────────────────────────────────────────────────────────

    def submit_query(
        self,
        question: str,
        repo: str,
        *,
        index_id: str | None = None,
        engine_id: str = "multihop_faster",
        additional_context: str = "",
        wiki_page: str | None = None,
        query_id: str | None = None,
    ) -> str:
        """POST /ada/query — submit a question.

        - When `query_id` is None, generates a fresh one and starts a new thread.
        - When `query_id` is provided, posts a follow-up to the existing thread.
          Re-using a query_id appends to its `queries[]` array on the server.

        engine_id: any value from `ENGINE_IDS` (use `resolve_engine` for aliases).
          Common: multihop_faster (fast), multihop (research), codemap.
        """
        if index_id is None:
            idx = self.get_index(repo)
            if idx is None:
                from .exceptions import NotFoundError
                raise NotFoundError(f"Repo not indexed on DeepWiki: {repo}")
            index_id = idx.id

        if wiki_page:
            user_query = (
                f"<relevant_context>This query was sent from the wiki page: "
                f"{wiki_page}.</relevant_context>{question}"
            )
        else:
            user_query = question

        if query_id is None:
            query_id = f"{_slugify_query(question)}_{uuid.uuid4()}"
        body = {
            "query_id": query_id,
            "user_query": user_query,
            "additional_context": additional_context,
            "repo_names": [repo],
            "repo_context_ids": [index_id],
            "engine_id": engine_id,
        }
        resp = self._post("/ada/query", json=body)
        if resp.json().get("status") != "success":
            raise DeepwikiError(f"Unexpected POST /ada/query response: {resp.text[:200]}")
        return query_id

    def follow_up(
        self,
        query_id: str,
        question: str,
        repo: str,
        *,
        index_id: str | None = None,
        engine_id: str = "multihop_faster",
        additional_context: str = "",
    ) -> str:
        """Append a follow-up question to an existing thread. Returns query_id."""
        return self.submit_query(
            question,
            repo,
            index_id=index_id,
            engine_id=engine_id,
            additional_context=additional_context,
            query_id=query_id,
        )

    def get_query(self, query_id: str) -> Query:
        """GET /ada/query/{id} — fetch current state of a submitted query."""
        resp = self._get(f"/ada/query/{quote(query_id, safe='')}")
        return Query.from_dict(resp.json())

    def stream_query(
        self,
        query_id: str,
        *,
        timeout: float = 300.0,
        backoff_initial: float = 2.0,
        backoff_factor: float = 1.5,
        backoff_max: float = 10.0,
        prior_count: int = 0,
    ) -> Iterator[Query]:
        """Yield Query snapshots as the server progresses pending → running → done.

        Implements exponential backoff per HARNESS.md §Polling: 2s→3s→4.5s→6.75s→10s.

        prior_count: ignore the first `prior_count` queries when judging "done"
        (used by follow-ups so we wait for the *latest* query to finish, not
        an earlier completed one in the same thread).
        """
        start = time.monotonic()
        delay = backoff_initial
        while True:
            q = self.get_query(query_id)
            yield q
            # For follow-ups: judge state from the LAST query, not the first.
            tail = q.queries[-1] if q.queries else None
            tail_state = tail.state if tail else "unknown"
            enough_queries = len(q.queries) > prior_count
            if enough_queries and tail_state in ("done", "complete", "error", "failed"):
                return
            if time.monotonic() - start >= timeout:
                from .exceptions import ServerError
                raise ServerError(
                    f"Query {query_id} did not complete within {timeout}s",
                    status_code=504,
                )
            time.sleep(delay)
            delay = min(delay * backoff_factor, backoff_max)

    def ask(
        self,
        question: str,
        repo: str,
        *,
        engine_id: str = "multihop_faster",
        additional_context: str = "",
        wiki_page: str | None = None,
        query_id: str | None = None,
        on_progress=None,
    ) -> Query:
        """Submit a question and poll until done.

        If `query_id` is provided, the question is appended as a follow-up to
        that existing thread; otherwise a new thread is created.

        The returned Query has its `_query_id` attribute set so callers can
        persist it for follow-ups.
        """
        # Track how many queries the thread had BEFORE this submission so the
        # poll loop knows when the *latest* turn finishes.
        prior_count = 0
        if query_id is not None:
            try:
                prior = self.get_query(query_id)
                prior_count = len(prior.queries)
            except Exception:
                prior_count = 0

        qid = self.submit_query(
            question,
            repo,
            engine_id=engine_id,
            additional_context=additional_context,
            wiki_page=wiki_page,
            query_id=query_id,
        )
        last = None
        for snap in self.stream_query(qid, prior_count=prior_count):
            last = snap
            if on_progress:
                on_progress(snap)
        assert last is not None
        # Attach for caller convenience (Session persistence, follow-ups)
        setattr(last, "_query_id", qid)
        return last

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, **kwargs) -> httpx.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> httpx.Response:
        return self._request("POST", path, **kwargs)

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_on_auth: bool = True,
        **kwargs,
    ) -> httpx.Response:
        # Preferred: cookies live on the client instance (not per-request).
        # Tests still pass cookies via kwargs for mock injection — preserve that.
        if "cookies" not in kwargs:
            for name, value in self._cookies.items():
                if name not in self._client.cookies:
                    self._client.cookies.set(name, value)
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise NetworkError(f"Connection failed: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request timed out: {exc}") from exc

        # Capture devin_client_uuid cookie for session reuse
        if "devin_client_uuid" in resp.cookies:
            self._cookies["devin_client_uuid"] = resp.cookies["devin_client_uuid"]

        # Auth retry: 401/403 → re-mint cookie and retry exactly once
        if resp.status_code in (401, 403) and retry_on_auth:
            self._client.cookies.clear()
            self._cookies.clear()
            return self._request(method, path, retry_on_auth=False, **kwargs)

        raise_for_status(resp)
        return resp

    def close(self) -> None:
        self._client.close()

    @property
    def cookies(self) -> dict:
        return dict(self._cookies)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── DeepWiki SSR HTML ─────────────────────────────────────────────────────────


class DeepwikiHTMLClient:
    """Fetch raw SSR HTML from deepwiki.com — wiki pages, repo overview, TOC."""

    BASE_URL = "https://deepwiki.com"

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=timeout, pool=timeout),
            headers={**_DEEPWIKI_HEADERS, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
        )

    def fetch_repo_html(self, repo: str) -> str:
        """GET /{owner}/{repo} → full SSR HTML (overview + sidebar TOC)."""
        return self._get(f"/{repo}").text

    def fetch_page_html(self, repo: str, slug: str) -> str:
        """GET /{owner}/{repo}/{slug} → wiki page HTML."""
        return self._get(f"/{repo}/{slug}").text

    def fetch_repo_overview(self, repo: str) -> RepoCard:
        """Quick metadata extraction from the overview HTML.

        DeepWiki renders "Last indexed: …" client-side via RSC, so it isn't in
        the SSR HTML we receive. The caller should layer Index.last_modified on
        top via DeepwikiClient.repo_overview() to populate `last_indexed`.
        """
        html = self.fetch_repo_html(repo)
        title_m = re.search(r"<title>([^<]+)</title>", html)
        last_m = re.search(r"Last indexed:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", html)
        commit_m = re.search(
            r"github\.com/" + re.escape(repo) + r"/commits/([0-9a-f]{6,40})", html
        )
        return RepoCard(
            repo=repo,
            title=(title_m.group(1).strip() if title_m else repo),
            last_indexed=(last_m.group(1) if last_m else None),
            indexed_commit=(commit_m.group(1) if commit_m else None),
            html=html,
        )

    def fetch_wiki_tree(self, repo: str) -> WikiTree:
        """Extract the sidebar TOC from /{owner}/{repo} HTML.

        Returns a WikiTree with each entry's slug + title + (optional) parent slug.
        """
        html = self.fetch_repo_html(repo)
        # Sidebar TOC items are <a href="/owner/repo/{slug}">{Title}</a>
        # Match anchor tags pointing into this repo's namespace
        prefix = f"/{repo}/"
        pattern = re.compile(
            r'<a[^>]+href="(' + re.escape(prefix) + r'[^"#?]+)"[^>]*>([^<]+)</a>',
            re.IGNORECASE,
        )
        seen = set()
        entries: list[Page] = []
        for href, title in pattern.findall(html):
            slug = href[len(prefix):]
            if slug in seen:
                continue
            seen.add(slug)
            entries.append(Page(repo=repo, slug=slug, title=title.strip(), markdown=None, html=None))
        return WikiTree(repo=repo, pages=entries)

    def fetch_page(self, repo: str, slug: str) -> Page:
        """Fetch a wiki page as raw HTML (caller pipes through unified).

        Title resolution priority:
          1. First <h1> inside the rendered body (the page heading)
          2. Slug → titlecased fallback
        We avoid the <title> tag because DeepWiki sets it to the repo name on
        every page rather than the page heading.
        """
        html = self.fetch_page_html(repo, slug)
        title = _derive_title_from_html(html) or _slug_to_title(slug)
        return Page(repo=repo, slug=slug, title=title, html=html, markdown=None)

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, **kwargs) -> httpx.Response:
        try:
            resp = self._client.get(path, **kwargs)
        except httpx.ConnectError as exc:
            raise NetworkError(f"Connection failed: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request timed out: {exc}") from exc
        raise_for_status(resp)
        return resp

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── Composite client (what commands typically use) ────────────────────────────


class DeepwikiClient:
    """Facade that owns both backends. Commands depend on this."""

    def __init__(self, cookies: dict | None = None, timeout: float = 30.0):
        self.ada = DevinAdaClient(cookies=cookies, timeout=timeout)
        self.html = DeepwikiHTMLClient(timeout=timeout)

    def close(self) -> None:
        self.ada.close()
        self.html.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Convenience pass-throughs ─────────────────────────────────────────────
    def search(self, q: str | None = None) -> list[Index]:
        return self.ada.list_public_indexes(search_repo=q)

    def get_index(self, repo: str) -> Index | None:
        return self.ada.get_index(repo)

    def repo_overview(self, repo: str) -> RepoCard:
        """Repo overview enriched with Index.last_modified when available.

        DeepWiki SSR HTML doesn't surface the index date directly (it's
        rendered client-side via RSC). The Devin Ada API DOES expose it via
        `last_modified` on each Index entry. This facade method merges both
        so the user gets a complete card in one call.
        """
        card = self.html.fetch_repo_overview(repo)
        if not card.last_indexed:
            try:
                idx = self.ada.get_index(repo)
                if idx and idx.last_modified:
                    card.last_indexed = idx.last_modified
                if idx and idx.commit_sha and not card.indexed_commit:
                    card.indexed_commit = idx.commit_sha
            except Exception:
                # Fail open — overview without date still useful
                pass
        return card

    def wiki_tree(self, repo: str) -> WikiTree:
        return self.html.fetch_wiki_tree(repo)

    def fetch_page(self, repo: str, slug: str) -> Page:
        return self.html.fetch_page(repo, slug)

    def ask(self, question: str, repo: str, **kwargs) -> Query:
        return self.ada.ask(question, repo, **kwargs)
