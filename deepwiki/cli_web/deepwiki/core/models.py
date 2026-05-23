"""Typed response models for cli-web-deepwiki.

Every Devin Ada API and DeepWiki HTML response has a corresponding dataclass.
Use Model.from_dict() for deserialization; Model.to_dict() for JSON output.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ── Devin Ada API ─────────────────────────────────────────────────────────────


@dataclass
class Index:
    """Entry in /ada/list_public_indexes response."""
    id: str                    # v1.9.9.5/PUBLIC/{owner}/{repo}/{commit_sha}
    repo_name: str
    last_modified: str | None = None
    description: str | None = None
    stargazers_count: int = 0
    language: str | None = None
    topics: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Index":
        return cls(
            id=d.get("id", ""),
            repo_name=d.get("repo_name", ""),
            last_modified=d.get("last_modified"),
            description=d.get("description"),
            stargazers_count=int(d.get("stargazers_count") or 0),
            language=d.get("language"),
            topics=list(d.get("topics") or []),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def commit_sha(self) -> str | None:
        parts = self.id.split("/")
        return parts[-1] if len(parts) >= 5 else None


@dataclass
class ResponseBlock:
    """Single typed block in Query.response[]."""
    type: str                  # chunk | reference | file_contents | stats | loading_indexes | module_call_id | playground_link | progress | tool_call
    data: Any

    @classmethod
    def from_dict(cls, d: dict) -> "ResponseBlock":
        return cls(type=d.get("type", ""), data=d.get("data"))

    def to_dict(self) -> dict:
        return {"type": self.type, "data": self.data}


@dataclass
class Reference:
    """Citation produced by Devin's response stream."""
    file_path: str             # "Repo {owner}/{repo}: {path}" or just "{path}"
    range_start: int = 0
    range_end: int = 0

    @classmethod
    def from_block_data(cls, d: dict) -> "Reference":
        return cls(
            file_path=d.get("file_path", ""),
            range_start=int(d.get("range_start") or 0),
            range_end=int(d.get("range_end") or 0),
        )

    def github_url(self, repo: str, commit: str) -> str | None:
        path = self.file_path
        if path.startswith("Repo "):
            after = path.split(":", 1)[-1].strip()
            path = after
        if not path:
            return None
        return (
            f"https://github.com/{repo}/blob/{commit}/{path}"
            f"?plain=1#L{self.range_start}-L{self.range_end}"
        )


@dataclass
class CodemapLocation:
    """Single code location within a codemap trace."""
    id: str
    path: str
    line_number: int
    line_content: str
    title: str
    description: str

    @classmethod
    def from_dict(cls, d: dict) -> "CodemapLocation":
        raw_path = d.get("path", "")
        # Strip {repo}:// URI prefix -> relative path
        if "://" in raw_path:
            raw_path = raw_path.split("://", 1)[1]
        return cls(
            id=d.get("id", ""),
            path=raw_path,
            line_number=int(d.get("lineNumber") or 0),
            line_content=d.get("lineContent", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CodemapTrace:
    """Single architectural trace in a codemap result."""
    id: str
    title: str
    description: str
    locations: list[CodemapLocation]
    text_diagram: str
    guide: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CodemapTrace":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            locations=[CodemapLocation.from_dict(loc) for loc in d.get("locations") or []],
            text_diagram=d.get("traceTextDiagram", ""),
            guide=d.get("traceGuide", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CodemapResult:
    """Parsed codemap engine response."""
    title: str
    traces: list[CodemapTrace]
    playground_links: list[str] = field(default_factory=list)

    @classmethod
    def from_query(cls, query: "Query") -> "CodemapResult":
        """Extract structured codemap data from a Query object."""
        traces = []
        playground_links = []
        title = ""

        if query.latest:
            for blk in query.latest.response:
                if blk.type == "chunk":
                    chunk_data = blk.data
                    if isinstance(chunk_data, str):
                        try:
                            import json
                            chunk_data = json.loads(chunk_data)
                        except (json.JSONDecodeError, TypeError):
                            continue
                    if isinstance(chunk_data, dict) and "traces" in chunk_data:
                        title = chunk_data.get("title", "")
                        traces = [CodemapTrace.from_dict(t) for t in chunk_data["traces"]]
                elif blk.type == "playground_link":
                    if isinstance(blk.data, str):
                        playground_links.append(blk.data)
                    elif isinstance(blk.data, dict):
                        playground_links.append(blk.data.get("url") or str(blk.data))

        return cls(title=title or query.title, traces=traces, playground_links=playground_links)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "traces": [t.to_dict() for t in self.traces],
            "playground_links": self.playground_links,
        }


@dataclass
class Query:
    """The result envelope returned by GET /ada/query/{id}."""
    title: str
    org_id: str | None
    queries: list["QueryItem"]

    @classmethod
    def from_dict(cls, d: dict) -> "Query":
        return cls(
            title=d.get("title", ""),
            org_id=d.get("org_id"),
            queries=[QueryItem.from_dict(q) for q in d.get("queries") or []],
        )

    @property
    def state(self) -> str:
        """State of the most recent query (handles follow-up threads)."""
        return self.latest.state if self.latest else "unknown"

    @property
    def primary(self) -> "QueryItem | None":
        """First query in the thread (initial question)."""
        return self.queries[0] if self.queries else None

    @property
    def latest(self) -> "QueryItem | None":
        """Most recent query in the thread (the one a follow-up just added)."""
        return self.queries[-1] if self.queries else None

    @property
    def turn_count(self) -> int:
        """Number of question/answer turns in this thread."""
        return len(self.queries)

    @staticmethod
    def _chunks_markdown(item: "QueryItem") -> str:
        parts: list[str] = []
        for blk in item.response:
            if blk.type == "chunk":
                if isinstance(blk.data, str):
                    parts.append(blk.data)
                elif isinstance(blk.data, dict) and "text" in blk.data:
                    parts.append(str(blk.data["text"]))
        return "".join(parts)

    @staticmethod
    def _thoughts(item: "QueryItem") -> list[str]:
        """Extract the agent reasoning trace (omni / agent / planning engines).

        Blocks come as paired thoughts_start / thoughts_end with chunks in between
        carrying the actual reasoning text. We capture each thought run separately.
        """
        out: list[str] = []
        in_thought = False
        buf: list[str] = []
        for blk in item.response:
            if blk.type == "thoughts_start":
                in_thought = True
                buf = []
            elif blk.type == "thoughts_end":
                if in_thought:
                    out.append("".join(buf).strip())
                in_thought = False
                buf = []
            elif blk.type == "chunk" and in_thought:
                if isinstance(blk.data, str):
                    buf.append(blk.data)
                elif isinstance(blk.data, dict) and "text" in blk.data:
                    buf.append(str(blk.data["text"]))
        # If thoughts_end was missed, flush whatever we have
        if in_thought and buf:
            out.append("".join(buf).strip())
        return [t for t in out if t]

    @staticmethod
    def _tool_calls(item: "QueryItem") -> list[dict]:
        """Extract tool call traces (paired tool_call_start / tool_call_complete)."""
        out: list[dict] = []
        for blk in item.response:
            if blk.type in ("tool_call_start", "tool_call_complete"):
                out.append({
                    "phase": blk.type.replace("tool_call_", ""),
                    "data": blk.data,
                })
        return out

    @staticmethod
    def _refs(item: "QueryItem") -> list[Reference]:
        out: list[Reference] = []
        for blk in item.response:
            if blk.type == "reference" and isinstance(blk.data, dict):
                out.append(Reference.from_block_data(blk.data))
        return out

    @property
    def answer_markdown(self) -> str:
        """Markdown answer to the most recent query.

        Excludes thoughts blocks — the answer is what the user sees in the UI.
        Use `thoughts` separately to inspect agentic reasoning traces.
        """
        if not self.latest:
            return ""
        # Suppress chunks emitted between thoughts_start/_end so the answer
        # doesn't get polluted by reasoning text.
        parts: list[str] = []
        in_thought = False
        for blk in self.latest.response:
            if blk.type == "thoughts_start":
                in_thought = True
            elif blk.type == "thoughts_end":
                in_thought = False
            elif blk.type == "chunk" and not in_thought:
                if isinstance(blk.data, str):
                    parts.append(blk.data)
                elif isinstance(blk.data, dict) and "text" in blk.data:
                    parts.append(str(blk.data["text"]))
        return "".join(parts)

    @property
    def references(self) -> list[Reference]:
        """References for the most recent query."""
        return self._refs(self.latest) if self.latest else []

    @property
    def thoughts(self) -> list[str]:
        """Agent reasoning trace for the most recent query (omni/agent/planning)."""
        return self._thoughts(self.latest) if self.latest else []

    @property
    def tool_calls(self) -> list[dict]:
        """Tool calls executed by the agent during the most recent query."""
        return self._tool_calls(self.latest) if self.latest else []

    @property
    def transcript(self) -> list[dict]:
        """Full thread as ordered Q/A pairs."""
        return [
            {
                "user_query": q.user_query,
                "engine_id": q.engine_id,
                "state": q.state,
                "answer": self._chunks_markdown(q),
                "references": [r.__dict__ for r in self._refs(q)],
            }
            for q in self.queries
        ]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "org_id": self.org_id,
            "state": self.state,
            "turn_count": self.turn_count,
            "answer": self.answer_markdown,
            "thoughts": self.thoughts,
            "tool_calls": self.tool_calls,
            "references": [r.__dict__ for r in self.references],
            "transcript": self.transcript,
            "queries": [q.to_dict() for q in self.queries],
        }


@dataclass
class QueryItem:
    """Single query inside Query.queries."""
    message_id: str
    user_query: str
    use_knowledge: bool
    engine_id: str
    model: str | None
    repo_names: list[str]
    repo_context_ids: list[str]
    repos: list[dict]
    response: list[ResponseBlock]
    error: str | None
    state: str
    redis_stream: str | None
    module_call_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "QueryItem":
        return cls(
            message_id=d.get("message_id", ""),
            user_query=d.get("user_query", ""),
            use_knowledge=bool(d.get("use_knowledge")),
            engine_id=d.get("engine_id", ""),
            model=d.get("model"),
            repo_names=list(d.get("repo_names") or []),
            repo_context_ids=list(d.get("repo_context_ids") or []),
            repos=list(d.get("repos") or []),
            response=[ResponseBlock.from_dict(b) for b in d.get("response") or []],
            error=d.get("error"),
            state=d.get("state") or "unknown",
            redis_stream=d.get("redis_stream"),
            module_call_id=d.get("module_call_id"),
        )

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "user_query": self.user_query,
            "engine_id": self.engine_id,
            "state": self.state,
            "model": self.model,
            "repo_names": self.repo_names,
            "repo_context_ids": self.repo_context_ids,
            "response": [b.to_dict() for b in self.response],
            "error": self.error,
        }


# ── DeepWiki HTML ─────────────────────────────────────────────────────────────


@dataclass
class RepoCard:
    """Quick metadata from the SSR repo overview page."""
    repo: str
    title: str
    last_indexed: str | None = None
    indexed_commit: str | None = None
    html: str | None = None

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "title": self.title,
            "last_indexed": self.last_indexed,
            "indexed_commit": self.indexed_commit,
            # html omitted for brevity in JSON output
        }


@dataclass
class Page:
    """A single wiki page. Set markdown after running the unified pipeline."""
    repo: str
    slug: str
    title: str
    html: str | None = None
    markdown: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"https://deepwiki.com/{self.repo}/{self.slug}"

    @property
    def parent_slug(self) -> str | None:
        """Sub-section pages like '3.1-...' nest under '3-...' — derive parent."""
        # number prefix: ^(\d+(?:\.\d+)*)-
        import re
        m = re.match(r"^(\d+(?:\.\d+)*)-", self.slug)
        if not m:
            return None
        num = m.group(1)
        if "." not in num:
            return None
        parent_num = num.rsplit(".", 1)[0]
        # We don't know the exact parent slug name — caller resolves via WikiTree
        return parent_num

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "slug": self.slug,
            "title": self.title,
            "url": self.url,
            "markdown": self.markdown,
            "metadata": self.metadata,
        }


@dataclass
class WikiTree:
    """Sidebar TOC of a DeepWiki repo."""
    repo: str
    pages: list[Page] = field(default_factory=list)

    def find(self, slug: str) -> Page | None:
        for p in self.pages:
            if p.slug == slug:
                return p
        return None

    @property
    def slugs(self) -> list[str]:
        return [p.slug for p in self.pages]

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "count": len(self.pages),
            "pages": [{"slug": p.slug, "title": p.title, "url": p.url} for p in self.pages],
        }
