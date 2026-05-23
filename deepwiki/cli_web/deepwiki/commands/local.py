"""`dw local` — local-first LLM code intelligence.

Self-contained command group: wiki download, architecture codemaps, symbol lookup.
All core logic uses stdlib only (no extra deps beyond click).

Usage:
    dw local org/repo                              # wiki download (default)
    dw local wiki org/repo                         # explicit wiki
    dw local codemap org/repo "trace the API"      # codemap via LLM
    dw local codemap --workspace . "trace dispatch" -m k2.6
    dw local lookup org/repo createRouter          # symbol wiki
    dw local lookup --workspace . --symbols        # list all symbols
"""
from __future__ import annotations

import json as _json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import click


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

PROVIDERS = {
    "go": {
        "url": "https://opencode.ai/zen/go/v1/chat/completions",
        "env_key": "OPENCODE_GO_API_KEY",
        "format": "openai",
        "models": {
            "flash": "deepseek-v4-flash",
            "pro": "deepseek-v4-pro",
            "k2.6": "kimi-k2.6",
        },
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
        "format": "openai",
        "models": {
            "flash": "gpt-4o-mini",
            "pro": "gpt-4o",
            "k2.6": "gpt-4o",
        },
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
        "format": "anthropic",
        "models": {
            "flash": "claude-haiku-4-5-20251001",
            "pro": "claude-sonnet-4-6",
            "k2.6": "claude-opus-4-7",
        },
    },
}

_MODEL_CHOICES = ["flash", "pro", "k2.6"]
_PROVIDER_CHOICES = list(PROVIDERS.keys())

CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".rs", ".go",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".swift", ".scala",
    ".r", ".m", ".mm", ".cs", ".fs", ".clj", ".erl", ".ex", ".exs",
}
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".tox", ".next", ".turbo", "coverage",
}


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(self, provider: str = "go", api_key: str | None = None,
                 model_id: str | None = None, model_tier: str = "pro"):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}. Choose from: {', '.join(PROVIDERS)}")
        cfg = PROVIDERS[provider]
        self.url = cfg["url"]
        self.fmt = cfg["format"]
        self.api_key = api_key or os.environ.get(cfg["env_key"], "")
        if not self.api_key:
            raise RuntimeError(f"No API key for {provider}. Set {cfg['env_key']} or pass --api-key.")
        self.model = model_id or cfg["models"].get(model_tier, cfg["models"]["pro"])
        self.provider = provider

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        if self.fmt == "openai":
            return self._openai_complete(system, user, temperature)
        return self._anthropic_complete(system, user, temperature)

    def _openai_complete(self, system: str, user: str, temperature: float) -> str:
        payload = _json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }).encode("utf-8")
        req = Request(self.url, data=payload, headers={
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "dw-cli/1.0",
        }, method="POST")
        try:
            with urlopen(req, timeout=180) as resp:
                data = _json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{self.provider} error {e.code}: {body}") from None
        except URLError as e:
            raise RuntimeError(f"Network error ({self.provider}): {e.reason}") from None

    def _anthropic_complete(self, system: str, user: str, temperature: float) -> str:
        payload = _json.dumps({
            "model": self.model,
            "max_tokens": 8192,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": temperature,
        }).encode("utf-8")
        req = Request(self.url, data=payload, headers={
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "User-Agent": "dw-cli/1.0",
        }, method="POST")
        try:
            with urlopen(req, timeout=180) as resp:
                data = _json.loads(resp.read())
            return data["content"][0]["text"]
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{self.provider} error {e.code}: {body}") from None
        except URLError as e:
            raise RuntimeError(f"Network error ({self.provider}): {e.reason}") from None


# ---------------------------------------------------------------------------
# Source file scanning
# ---------------------------------------------------------------------------

def _gather_files(workspace: Path, max_files: int = 50,
                  max_lines_per_file: int = 300) -> list[tuple[Path, list[str]]]:
    files: list[tuple[Path, list[str]]] = []
    for p in sorted(workspace.rglob("*")):
        if len(files) >= max_files:
            break
        if p.is_dir() or p.suffix not in CODE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
            if len(lines) > max_lines_per_file:
                lines = lines[:max_lines_per_file]
            files.append((p, lines))
        except Exception:
            continue
    return files


def _build_workspace_snapshot(files: list[tuple[Path, list[str]]], workspace: Path) -> str:
    parts: list[str] = []
    for path, lines in files:
        rel = path.relative_to(workspace)
        parts.append(f"\n--- {rel} ---\n")
        for i, line in enumerate(lines, 1):
            parts.append(f"{i:4d}| {line}\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Codemap data structures
# ---------------------------------------------------------------------------

@dataclass
class _Location:
    id: str
    lineContent: str
    path: str
    lineNumber: int
    title: str
    description: str = ""


@dataclass
class _Trace:
    id: str
    title: str
    description: str = ""
    locations: list[_Location] = field(default_factory=list)
    traceTextDiagram: str = ""
    traceGuide: str = ""


@dataclass
class _MapArtifact:
    schemaVersion: str = "1.0"
    id: str = ""
    stableId: str = ""
    title: str = ""
    description: str = ""
    traces: list[_Trace] = field(default_factory=list)
    mermaidDiagram: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Codemap LLM prompts
# ---------------------------------------------------------------------------

_MAP_SYSTEM_PROMPT = """You are a code-map generation engine. Your job is to produce structured maps that document control flow and data flow across codebases.

Rules:
- Be terse and precise.
- Prefer imperative lines over definitions.
- Each trace should answer "what happens when".
- Plan first, then emit.
- Only emit JSON within <CODEMAP> tags after the <PLAN> section.
"""

_MAP_GENERATION_INSTRUCTION = """Now generate a codemap with the following object structure:

{
  "title": "string",
  "traces": [
    {
      "id": "string",
      "title": "string",
      "description": "string",
      "locations": [
        {
          "id": "string",
          "lineContent": "string",
          "path": "string",
          "lineNumber": number,
          "title": "string",
          "description": "string"
        }
      ]
    }
  ],
  "description": "string"
}

Guidance:
- Within a trace, avoid outputting a bunch of locations from all the same file.
- Pick meaningful, load-bearing lines whose line content is both significant and informative.
- Traces should tell stories — they should answer questions of the form "what happens when".
- Pick lines of code that actually do things. Imperative lines are preferred over definitions.
- Avoid highlighting lines that merely define classes or functions; instead pick lines that call functions or instantiate classes.
- If there are multiple disconnected systems, make it clear in trace titles.

Output format:
<PLAN>
your brainstorming goes here
</PLAN>
<CODEMAP>
codemap JSON content goes here
</CODEMAP>

Do not use tools. Do not use code fences. Only emit the JSON within the CODEMAP XML tags.
"""

_TRACE_DIAGRAM_PROMPT = """For trace {trace_id} "{trace_title}", draw a concise tree showing how the locations relate. Add context nodes as necessary.

Decorate highlighted trace locations like "node title <-- 1a". Use each location id at least once. Limit the tree to 5-15 nodes. Avoid going past depth 10.

Output within <TRACE_TEXT_DIAGRAM> tags."""

_TRACE_GUIDE_PROMPT = """For trace {trace_id} "{trace_title}", write a brief trace guide (2-4 paragraphs) explaining the motivation and details. Use Markdown. Reference locations like [1a] or [2b].

Output within <TRACE_GUIDE> tags."""

_MERMAID_PROMPT = """Now make a Mermaid diagram for the entire codemap. Use node ids like "1a:" at the front of labels. Use subgraphs and annotations.

Try to avoid making the diagram too linear; prefer branching / breadth / shallow graphs. Show non-trivial connections across traces. Label important edges (present tense). Color different subgraphs with these fills:
#eebefa #fcc2d7 #d0bfff #b2f2bb #ffec99 #ffd8a8 #99e9f2 #a5d8ff

Output within ```mermaid fences."""


# ---------------------------------------------------------------------------
# Codemap generation pipeline
# ---------------------------------------------------------------------------

def _extract_tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_codeblock(text: str, language: str = "") -> str:
    m = re.search(rf"```{language}\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _generate_map(workspace: Path, prompt: str, client: LLMClient,
                  max_files: int = 50) -> _MapArtifact:
    files = _gather_files(workspace, max_files=max_files)
    if not files:
        raise RuntimeError(f"No source files found in {workspace}")
    snapshot = _build_workspace_snapshot(files, workspace)

    user_prompt = f"""<user_prompt>{prompt}</user_prompt>

<workspace_information>
Below is a snapshot of the codebase file structure and contents:
{snapshot}
</workspace_information>

<about_codemaps>
Codemaps are structured traces that document control flow and data flow across complex systems. They should deeply explore codebases by following function calls, async tasks, and inter-service communication. Good codemaps break down complex flows into logical traces of 2-10 locations each, with clear relationships.
</about_codemaps>

{_MAP_GENERATION_INSTRUCTION}
"""
    click.echo("  LLM call 1: initial codemap...", err=True)
    response = client.complete(_MAP_SYSTEM_PROMPT, user_prompt, temperature=0.3)

    codemap_json_str = _extract_tag(response, "CODEMAP")
    if not codemap_json_str:
        raise RuntimeError("No <CODEMAP> tag found in LLM response.")

    raw = _json.loads(codemap_json_str)
    artifact = _MapArtifact(
        id=str(uuid.uuid4()),
        stableId=str(uuid.uuid4()),
        title=raw.get("title", ""),
        description=raw.get("description", ""),
        metadata={
            "generationSource": "dw",
            "generationTimestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "provider": client.provider,
            "model": client.model,
            "originalPrompt": prompt,
        },
    )

    for t in raw.get("traces", []):
        trace = _Trace(
            id=t.get("id", ""),
            title=t.get("title", ""),
            description=t.get("description", ""),
            locations=[
                _Location(
                    id=loc.get("id", ""),
                    lineContent=loc.get("lineContent", ""),
                    path=loc.get("path", ""),
                    lineNumber=loc.get("lineNumber", 0),
                    title=loc.get("title", ""),
                    description=loc.get("description", ""),
                )
                for loc in t.get("locations", [])
            ],
        )
        artifact.traces.append(trace)

    total_calls = 1 + 2 * len(artifact.traces) + 1
    call_num = 1

    for trace in artifact.traces:
        call_num += 1
        locs_str = "\n".join(f"- {loc.id}: {loc.path}:{loc.lineNumber} — {loc.title}" for loc in trace.locations)
        dp = (
            f"Map: {artifact.title}\nTrace {trace.id}: {trace.title}\n"
            f"Locations:\n{locs_str}\n\n"
            f"{_TRACE_DIAGRAM_PROMPT.format(trace_id=trace.id, trace_title=trace.title)}"
        )
        click.echo(f"  LLM call {call_num}/{total_calls}: diagram for trace {trace.id}...", err=True)
        trace.traceTextDiagram = _extract_tag(client.complete(_MAP_SYSTEM_PROMPT, dp, 0.2), "TRACE_TEXT_DIAGRAM")

    for trace in artifact.traces:
        call_num += 1
        locs_str = "\n".join(f"- {loc.id}: {loc.path}:{loc.lineNumber} — {loc.lineContent}" for loc in trace.locations)
        gp = (
            f"Map: {artifact.title}\nTrace {trace.id}: {trace.title}\n"
            f"Description: {trace.description}\nLocations:\n{locs_str}\n\n"
            f"{_TRACE_GUIDE_PROMPT.format(trace_id=trace.id, trace_title=trace.title)}"
        )
        click.echo(f"  LLM call {call_num}/{total_calls}: guide for trace {trace.id}...", err=True)
        trace.traceGuide = _extract_tag(client.complete(_MAP_SYSTEM_PROMPT, gp, 0.3), "TRACE_GUIDE")

    call_num += 1
    traces_summary = "\n\n".join(
        f"Trace {t.id}: {t.title}\n" + "\n".join(
            f"  {loc.id}: {loc.path}:{loc.lineNumber} — {loc.title}" for loc in t.locations
        ) for t in artifact.traces
    )
    mp = (
        f"Map: {artifact.title}\nDescription: {artifact.description}\n"
        f"Traces:\n{traces_summary}\n\n{_MERMAID_PROMPT}"
    )
    click.echo(f"  LLM call {call_num}/{total_calls}: mermaid diagram...", err=True)
    mermaid_resp = client.complete(_MAP_SYSTEM_PROMPT, mp, 0.2)
    artifact.mermaidDiagram = _extract_codeblock(mermaid_resp, "mermaid") or _extract_codeblock(mermaid_resp)

    return artifact


# ---------------------------------------------------------------------------
# Symbol lookup
# ---------------------------------------------------------------------------

def _find_symbol(symbol: str, workspace: Path) -> tuple[Path, int, list[str]] | None:
    for p in sorted(workspace.rglob("*")):
        if not p.is_file() or p.suffix not in CODE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(rf"\b{re.escape(symbol)}\b", line):
                stripped = line.strip()
                if any(stripped.startswith(kw) for kw in (
                    "def ", "class ", "const ", "let ", "var ", "function ",
                    "func ", "type ", "interface ", "struct ", "enum ",
                )):
                    return p, i, lines
                if "=" in stripped and not stripped.startswith("#") and not stripped.startswith("//"):
                    return p, i, lines
    return None


def _find_callers(symbol: str, def_path: Path, workspace: Path) -> list[tuple[Path, int, int, list[str]]]:
    callers: list[tuple[Path, int, int, list[str]]] = []
    for p in sorted(workspace.rglob("*")):
        if not p.is_file() or p.suffix not in CODE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(rf"\b{re.escape(symbol)}\b", line):
                start = i
                for j in range(i - 1, 0, -1):
                    if re.match(r"^(\s*def\s+|\s*class\s+|\s*function\s+|\s*func\s+|\s*pub\s+fn\s+)", lines[j - 1]):
                        start = j
                        break
                end = min(i + 8, len(lines))
                callers.append((p, start, end, lines[start - 1:end]))
                break
    return callers[:5]


def _find_references(symbol: str, workspace: Path) -> list[tuple[Path, int, list[str]]]:
    refs: list[tuple[Path, int, list[str]]] = []
    for p in sorted(workspace.rglob("*")):
        if not p.is_file() or p.suffix not in CODE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(rf"\b{re.escape(symbol)}\b", line):
                start = max(i - 2, 1)
                end = min(i + 2, len(lines))
                refs.append((p, i, lines[start - 1:end]))
                if len(refs) >= 10:
                    return refs
    return refs


def _list_symbols(workspace: Path, max_files: int = 100) -> list[tuple[str, str, int]]:
    pat = re.compile(
        r"^(?:export\s+)?(?:pub\s+)?(?:async\s+)?"
        r"(?:def|class|function|func|fn|const|let|var|type|interface|struct|enum)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)"
    )
    symbols: list[tuple[str, str, int]] = []
    count = 0
    for p in sorted(workspace.rglob("*")):
        if count >= max_files:
            break
        if not p.is_file() or p.suffix not in CODE_EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        count += 1
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        rel = str(p.relative_to(workspace))
        for i, line in enumerate(lines, 1):
            m = pat.match(line.strip())
            if m:
                symbols.append((m.group(1), rel, i))
    return symbols


def _build_context_bundle(symbol: str, workspace: Path) -> str:
    found = _find_symbol(symbol, workspace)
    if not found:
        raise RuntimeError(f"Symbol '{symbol}' not found in {workspace}")
    def_path, def_line, def_lines = found
    callers = _find_callers(symbol, def_path, workspace)
    refs = _find_references(symbol, workspace)

    parts: list[str] = []
    parts.append(f"=== File Context for '{symbol}' ===")
    parts.append(f"File: {def_path}\n")
    for i, line in enumerate(def_lines, 1):
        parts.append(f"{i:4d}| {line}")

    parts.append(f"\n=== Symbol Definition: {symbol} at line {def_line} ===")
    parts.append(f"{def_line:4d}| {def_lines[def_line - 1]}")

    if callers:
        parts.append(f"\n=== Callers ({len(callers)}) ===")
        for idx, (path, start, end, clines) in enumerate(callers, 1):
            name = clines[0].strip().split("(")[0].split()[-1] if clines else "unknown"
            parts.append(f"\nCaller {idx}: {name} ({path}:{start}-{end})")
            for j, line in enumerate(clines, start):
                parts.append(f"{j:4d}| {line}")

    if refs:
        parts.append(f"\n=== References ({len(refs)}) ===")
        for idx, (path, line, rlines) in enumerate(refs, 1):
            parts.append(f"\nRef {idx}: {path}:{line}")
            for j, l in enumerate(rlines, max(line - 2, 1)):
                parts.append(f"{j:4d}| {l}")

    return "\n".join(parts)


_WIKI_SYSTEM_PROMPT = """You are a technical documentation engine that produces symbol-grounded Wiki-style articles.

Rules:
- Be precise, factual, and concise.
- Reproduce code snippets accurately.
- Include type, value, and scope information when inferable.
- Suggest 3 follow-up questions at the end.
- Output in Markdown."""


def _build_wiki_user_prompt(symbol: str, context_bundle: str) -> str:
    return f"""=== Symbol Documentation Request ===
Symbol: {symbol}

{context_bundle}

Generate a Wiki-style article for '{symbol}' with these sections:

1. **Introduction** — What the symbol is and its role in the codebase.
2. **Definition** — Reproduce the relevant code block.
3. **Basic Info** — Type, value, scope, and any other inferable metadata.
4. **Example Usages** — Show how the symbol is used with code snippets.
5. **See Also** — List 2-5 related symbols with brief explanations.
6. **Follow-up Questions** — Exactly 3 questions for further exploration.

Use standard Markdown with fenced code blocks.
"""


def _generate_lookup(workspace: Path, symbol: str, client: LLMClient) -> str:
    bundle = _build_context_bundle(symbol, workspace)
    user_prompt = _build_wiki_user_prompt(symbol, bundle)
    return client.complete(_WIKI_SYSTEM_PROMPT, user_prompt, temperature=0.2)


# ---------------------------------------------------------------------------
# RSC fetching and parsing
# ---------------------------------------------------------------------------

def _fetch_rsc(org: str, repo: str) -> bytes:
    url = f"https://deepwiki.com/{org}/{repo}"
    req = Request(url, headers={
        "RSC": "1",
        "Next-Router-State-Tree": "%5B%22%22%5D",
        "User-Agent": "Mozilla/5.0 (compatible; dw/2.0)",
    })
    try:
        with urlopen(req, timeout=60) as resp:
            return resp.read()
    except HTTPError as e:
        if e.code == 404:
            raise click.ClickException(f"repository '{org}/{repo}' not found on DeepWiki")
        raise click.ClickException(f"HTTP error {e.code}: {e.reason}")
    except URLError as e:
        raise click.ClickException(f"Network error: {e.reason}")


def _build_trecord_map(data: bytes) -> dict[str, str]:
    records = {}
    i = 0
    while i < len(data):
        nl = data.find(b"\n", i)
        if nl == -1:
            nl = len(data)
        line_start = data[i:min(i + 80, nl)]
        m = re.match(rb"^([0-9a-fA-F]+):T([0-9a-fA-F]+),", line_start)
        if m:
            record_id = m.group(1).decode()
            byte_len = int(m.group(2), 16)
            content_start = i + m.end()
            content = data[content_start:content_start + byte_len]
            records[record_id] = content.decode("utf-8", errors="replace")
            i = content_start + byte_len
            if i < len(data) and data[i:i + 1] == b"\n":
                i += 1
            continue
        i = nl + 1
    return records


def _extract_pages(data: bytes) -> list[dict]:
    text = data.decode("utf-8", errors="replace")
    pattern = re.compile(r'"pages"\s*:\s*\[')
    for m in pattern.finditer(text):
        start = m.end() - 1
        depth = 0
        for j in range(start, min(start + 500_000, len(text))):
            if text[j] == "[":
                depth += 1
            elif text[j] == "]":
                depth -= 1
            if depth == 0:
                arr_str = text[start:j + 1]
                arr_str = re.sub(r'"\$([0-9a-fA-F]+)"', r'"\1"', arr_str)
                try:
                    pages = _json.loads(arr_str)
                    if pages and isinstance(pages[0], dict):
                        return pages
                except (_json.JSONDecodeError, IndexError):
                    pass
                break
    entries = re.findall(
        r'\{"page_plan"\s*:\s*\{"id"\s*:\s*"([^"]+)"\s*,\s*"title"\s*:\s*"([^"]+)"\}\s*,\s*"content"\s*:\s*"\$?([0-9a-fA-F]+)"\}',
        text,
    )
    if entries:
        return [{"page_plan": {"id": pid, "title": title}, "content": ref} for pid, title, ref in entries]
    raise click.ClickException("Could not find pages structure in RSC response. DeepWiki may have changed format.")


def _resolve_content(page: dict, trecords: dict[str, str]) -> str | None:
    ref = page.get("content", "")
    if isinstance(ref, str):
        ref = ref.lstrip("$")
    if ref in trecords:
        return trecords[ref]
    try:
        hex_ref = format(int(ref), "x")
        if hex_ref in trecords:
            return trecords[hex_ref]
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Page content transformation for lat.md
# ---------------------------------------------------------------------------

def _sanitize_stem(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*()]+', "-", title)
    name = re.sub(r"\s+", "-", name).strip("-")
    name = re.sub(r"-{2,}", "-", name)
    return name[:100] if name else "untitled"


def _extract_details_sources(content: str) -> tuple[str, set[str]]:
    source_paths: set[str] = set()

    def _collect(m: re.Match) -> str:
        block = m.group(0)
        for link_m in re.finditer(r'\[([^\]]+)\]\(https://github\.com/[^)]+\)', block):
            path = link_m.group(1)
            if not path.endswith(".md"):
                source_paths.add(path)
        for link_m in re.finditer(r'\[([^\]]+)\]\(([^)]*)\)', block):
            path = link_m.group(1)
            href = link_m.group(2)
            if href.startswith("http"):
                continue
            if not path.endswith(".md") and "/" in path:
                source_paths.add(path)
        return ""

    cleaned = re.sub(r'<details>.*?</details>\s*', _collect, content, flags=re.DOTALL)
    return cleaned.lstrip("\n"), source_paths


def _strip_h1(content: str) -> str:
    lines = content.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return "\n".join(lines[i + 1:]).lstrip("\n")
        break
    return content


def _build_anchor_map(pages: list[dict]) -> dict[str, str]:
    mapping = {}
    for page in pages:
        plan = page.get("page_plan", page)
        page_id = plan.get("id", "0")
        title = plan.get("title", "Untitled")
        stem = f"{page_id}-{_sanitize_stem(title)}"
        mapping[page_id] = stem
    return mapping


def _convert_anchor_refs(content: str, anchor_map: dict[str, str]) -> str:
    def _replace(m: re.Match) -> str:
        text = m.group(1)
        anchor = m.group(2)
        if anchor in anchor_map:
            return f"[[{anchor_map[anchor]}|{text}]]"
        return m.group(0)
    return re.sub(r'\[([^\]]+)\]\(#([0-9]+(?:\.[0-9]+)*)\)', _replace, content)


def _convert_source_citations(content: str) -> tuple[str, set[str]]:
    source_paths: set[str] = set()

    def _make_link(ref: str) -> str | None:
        path = re.sub(r':[0-9].*$', '', ref)
        if path and not path.startswith("#"):
            source_paths.add(path)
            return f"[`{path}`](src/{path})"
        return None

    def _replace_single(m: re.Match) -> str:
        result = _make_link(m.group(1))
        return result if result else m.group(0)

    def _replace_double(m: re.Match) -> str:
        result = _make_link(m.group(1))
        return result if result else m.group(0)

    content = re.sub(r'\[\[([^\]\n]+)\]\]\(\)', _replace_double, content)
    content = re.sub(r'\[([^\]\n]+)\]\(\)', _replace_single, content)
    return content, source_paths


def _transform_page(content: str, anchor_map: dict[str, str]) -> tuple[str, set[str]]:
    all_sources: set[str] = set()
    content, detail_sources = _extract_details_sources(content)
    all_sources.update(detail_sources)
    content = _strip_h1(content)
    content = _convert_anchor_refs(content, anchor_map)
    content, citation_sources = _convert_source_citations(content)
    all_sources.update(citation_sources)
    stripped = content.lstrip("\n")
    if stripped and stripped[0] == "#":
        content = stripped
    return content.rstrip("\n") + "\n", all_sources


# ---------------------------------------------------------------------------
# lat.md index generation
# ---------------------------------------------------------------------------

def _generate_lat_index(org: str, repo: str,
                        page_entries: list[tuple[str, str, str]],
                        overview_content: str | None) -> str:
    identity = f"{org}/{repo} — DeepWiki-sourced documentation."
    if overview_content:
        cleaned = re.sub(r'<details>.*?</details>', '', overview_content, flags=re.DOTALL)
        for para in cleaned.split("\n\n"):
            para = para.strip().lstrip("#").strip()
            if len(para) > 30 and not para.startswith("<") and not para.startswith("```") and not para.startswith("|"):
                identity = para[:250]
                break
    lines = [f"# {org}/{repo}", "", identity, ""]
    sections: dict[str, list[tuple[str, str, str]]] = {}
    for page_id, title, stem in page_entries:
        section_key = page_id.split(".")[0]
        sections.setdefault(section_key, []).append((page_id, title, stem))
    for section_key in sorted(sections.keys(), key=lambda x: (int(x) if x.isdigit() else 999, x)):
        items = sections[section_key]
        top_item = items[0]
        lines.append(f"## {top_item[1]}")
        lines.append("")
        lines.append(f"Section {section_key} documentation pages.")
        lines.append("")
        for _, title, stem in items:
            lines.append(f"- [[{stem}]]")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# opensrc integration
# ---------------------------------------------------------------------------

def _fetch_workspace(org: str, repo: str) -> str | None:
    if not shutil.which("opensrc"):
        click.echo("  Warning: opensrc not found — install: npm install -g opensrc", err=True)
        return None
    click.echo(f"  Fetching source via opensrc {org}/{repo}...")
    try:
        result = subprocess.run(
            ["opensrc", "fetch", f"{org}/{repo}"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            click.echo(f"  Warning: opensrc fetch failed: {result.stderr.strip()}", err=True)
            return None
    except subprocess.TimeoutExpired:
        click.echo("  Warning: opensrc fetch timed out", err=True)
        return None
    try:
        result = subprocess.run(
            ["opensrc", "path", f"{org}/{repo}"],
            capture_output=True, text=True, timeout=10,
        )
        path = result.stdout.strip()
        if path and os.path.isdir(path):
            click.echo(f"  Workspace: {path}")
            return path
        click.echo(f"  Warning: opensrc path returned invalid directory: {path}", err=True)
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _setup_source_symlink(org: str, repo: str, vault_dir: str,
                          workspace_path: str | None = None) -> bool:
    if workspace_path is None:
        workspace_path = _fetch_workspace(org, repo)
    if not workspace_path:
        return False
    symlink_target = os.path.join(vault_dir, "src")
    if os.path.exists(symlink_target) or os.path.islink(symlink_target):
        os.remove(symlink_target)
    os.symlink(workspace_path, symlink_target)
    click.echo(f"  src → {workspace_path}")
    return True


def _run_lat_check(vault_dir: str) -> None:
    if not shutil.which("lat"):
        return
    click.echo("\n  Running lat check md...")
    try:
        result = subprocess.run(
            ["lat", "check", "md"],
            cwd=vault_dir, capture_output=True, text=True, timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        if output:
            for line in output.split("\n"):
                click.echo(f"    {line}")
        if result.returncode == 0:
            click.echo("  lat check md: PASS")
        else:
            click.echo(f"  lat check md: {result.returncode} issue(s) — review above")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        click.echo("  Warning: lat check md timed out or failed", err=True)


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

def _codemap_to_markdown(artifact: _MapArtifact, org: str, repo: str,
                         query: str, has_source: bool,
                         workspace_root: str | None = None) -> str:
    title = artifact.title or "Architecture Codemap"
    prov = artifact.metadata.get("provider", "LLM")
    model = artifact.metadata.get("model", "unknown")
    if org == "local":
        header = f"Codemap for **{repo}** (local workspace) — {prov}/{model}."
    else:
        header = f"Codemap for [{org}/{repo}](https://github.com/{org}/{repo}) — {prov}/{model}."
    lines = [f"# {title}", "", header, "", f"> **Query:** {query}", ""]
    for trace in artifact.traces:
        lines.append(f"## Trace {trace.id}: {trace.title}")
        lines.append("")
        if trace.description:
            lines.append(trace.description)
            lines.append("")
        if trace.traceTextDiagram:
            lines.append("```")
            lines.append(trace.traceTextDiagram)
            lines.append("```")
            lines.append("")
        if trace.locations:
            lines.append("### Locations")
            lines.append("")
            for loc in trace.locations:
                path = loc.path
                if workspace_root and os.path.isabs(path):
                    path = os.path.relpath(path, workspace_root)
                ln = loc.lineNumber
                if has_source:
                    lines.append(f"- **{loc.id}** [`{path}:{ln}`](src/{path}) — {loc.title}")
                else:
                    lines.append(f"- **{loc.id}** `{path}:{ln}` — {loc.title}")
                if loc.description and loc.description != loc.title:
                    lines.append(f"  {loc.description}")
            lines.append("")
        if trace.traceGuide:
            lines.append("### Guide")
            lines.append("")
            lines.append(trace.traceGuide)
            lines.append("")
    if artifact.mermaidDiagram:
        lines.append("## Architecture Diagram")
        lines.append("")
        lines.append("```mermaid")
        lines.append(artifact.mermaidDiagram)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _update_lat_index(lat_dir: str, section: str, section_desc: str, slug: str) -> None:
    index_path = os.path.join(lat_dir, "lat.md")
    if not os.path.isfile(index_path):
        return
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    wikilink = f"- [[{slug}]]\n"
    header = f"## {section}"
    if header in content:
        parts = content.split(header, 1)
        after = parts[1]
        next_section = re.search(r'\n## ', after)
        if next_section:
            pos = next_section.start()
            after = after[:pos] + wikilink + after[pos:]
        else:
            after = after.rstrip("\n") + "\n" + wikilink + "\n"
        content = parts[0] + header + after
    else:
        content = content.rstrip("\n") + f"\n\n{header}\n\n{section_desc}\n\n{wikilink}\n"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    click.echo(f"  Updated: lat.md/lat.md (added {section.lower()} link)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_repo(repo_input: str) -> tuple[str, str]:
    repo_input = repo_input.strip().rstrip("/")
    m = re.match(r"(?:https?://)?(?:www\.)?deepwiki\.com/([^/]+)/([^/]+)", repo_input)
    if m:
        return m.group(1), m.group(2)
    if "/" in repo_input and len(repo_input.split("/")) == 2:
        parts = repo_input.split("/")
        return parts[0], parts[1]
    raise click.ClickException(f"Cannot parse '{repo_input}'. Use org/repo or a deepwiki.com URL.")


def _resolve_workspace(workspace: str | None, org: str, repo: str) -> str:
    if workspace:
        ws = os.path.abspath(workspace)
        if not os.path.isdir(ws):
            raise click.ClickException(f"Workspace directory not found: {ws}")
        return ws
    path = _fetch_workspace(org, repo)
    if not path:
        raise click.ClickException(
            f"Could not fetch source for {org}/{repo} via opensrc.\n"
            "Install opensrc (npm install -g opensrc) or use --workspace."
        )
    return path


def _make_client(provider: str, model_tier: str, model_id: str | None,
                 api_key: str | None) -> LLMClient:
    return LLMClient(provider=provider, api_key=api_key,
                     model_id=model_id, model_tier=model_tier)


# ---------------------------------------------------------------------------
# Click group with default subcommand
# ---------------------------------------------------------------------------

class _DefaultGroup(click.Group):
    """Group that defaults to 'wiki' when the first arg isn't a known subcommand."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["wiki"] + args
        return super().parse_args(ctx, args)


@click.group(cls=_DefaultGroup, invoke_without_command=True)
@click.pass_context
def local(ctx: click.Context) -> None:
    """Local-first LLM code intelligence.

    \b
    Subcommands:
      wiki      Download DeepWiki pages into lat.md (default)
      codemap   Generate architecture codemap via LLM
      lookup    Generate symbol documentation via LLM

    \b
    Examples:
      dw local org/repo                              # wiki (default)
      dw local codemap org/repo "trace the API"
      dw local codemap --workspace . "trace it" -m k2.6
      dw local lookup org/repo createRouter
      dw local lookup --workspace . --symbols
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# Shared option decorator for LLM subcommands
# ---------------------------------------------------------------------------

def _llm_options(f):
    f = click.option("-p", "--provider", type=click.Choice(_PROVIDER_CHOICES),
                     default="go", help="LLM provider (default: go).")(f)
    f = click.option("-m", "--model", "model_tier", type=click.Choice(_MODEL_CHOICES),
                     default="pro", help="Model tier: flash, pro, k2.6 (default: pro).")(f)
    f = click.option("--model-id", default=None,
                     help="Raw model ID override (ignores -m).")(f)
    f = click.option("--api-key", default=None, envvar="DW_API_KEY",
                     help="API key (default: from provider env var).")(f)
    f = click.option("--workspace", "-w", default=None, type=click.Path(exists=True, file_okay=False),
                     help="Local source directory (skip opensrc).")(f)
    return f


# ---------------------------------------------------------------------------
# Subcommand: wiki (default)
# ---------------------------------------------------------------------------

@local.command()
@click.argument("repo")
@click.option("-o", "--output", default=None, help="Output directory (default: <repo>).")
@click.option("--no-source", is_flag=True, help="Skip opensrc integration.")
@click.option("--no-lat-check", is_flag=True, help="Skip lat check md.")
def wiki(repo: str, output: str | None, no_source: bool, no_lat_check: bool) -> None:
    """Download DeepWiki pages into a lat.md knowledge graph."""
    org, repo_name = _parse_repo(repo)
    vault_dir = output or repo_name
    os.makedirs(vault_dir, exist_ok=True)

    click.echo(f"Fetching DeepWiki for {org}/{repo_name}...")
    raw = _fetch_rsc(org, repo_name)
    click.echo(f"  RSC payload: {len(raw):,} bytes")

    trecords = _build_trecord_map(raw)
    click.echo(f"  T-records: {len(trecords)}")

    pages = _extract_pages(raw)
    click.echo(f"  Pages: {len(pages)}")

    if not pages:
        raise click.ClickException("No pages found.")

    has_source = False
    if not no_source:
        has_source = _setup_source_symlink(org, repo_name, vault_dir)

    anchor_map = _build_anchor_map(pages)

    lat_dir = os.path.join(vault_dir, "lat.md")
    os.makedirs(lat_dir, exist_ok=True)

    page_entries: list[tuple[str, str, str]] = []
    all_source_paths: set[str] = set()
    overview_raw: str | None = None
    skipped: list[tuple[str, str]] = []

    click.echo("\nProcessing pages:")
    for page in pages:
        plan = page.get("page_plan", page)
        page_id = plan.get("id", "0")
        title = plan.get("title", "Untitled")
        raw_content = _resolve_content(page, trecords)

        if not raw_content:
            skipped.append((page_id, title))
            click.echo(f"  [{page_id}] {title} — SKIPPED (content ref not resolved)")
            continue

        if page_id == "1" or (not overview_raw and "." not in page_id):
            overview_raw = raw_content

        stem = f"{page_id}-{_sanitize_stem(title)}"
        transformed, sources = _transform_page(raw_content, anchor_map)
        all_source_paths.update(sources)

        filepath = os.path.join(lat_dir, f"{stem}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
            f.write(transformed)

        page_entries.append((page_id, title, stem))
        click.echo(f"  [{page_id}] {title} → lat.md/{stem}.md ({len(transformed):,} chars)")

    index_content = _generate_lat_index(org, repo_name, page_entries, overview_raw)
    index_path = os.path.join(lat_dir, "lat.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)
    click.echo(f"\n  lat.md/lat.md index ({len(page_entries)} entries)")

    if all_source_paths:
        n = len(all_source_paths)
        resolved = sum(1 for p in all_source_paths
                       if has_source and os.path.exists(os.path.join(vault_dir, "src", p)))
        click.echo(f"  Source references: {n} paths found, {resolved} resolve to src/")

    if not no_lat_check:
        _run_lat_check(vault_dir)

    click.echo(f"\nDone: {len(page_entries)} pages → {vault_dir}/lat.md/")
    if has_source:
        click.echo(f"  Source code: {vault_dir}/src → opensrc cache")
    if skipped:
        click.echo(f"  Skipped: {len(skipped)} pages (content refs not resolved)")


# ---------------------------------------------------------------------------
# Subcommand: codemap
# ---------------------------------------------------------------------------

@local.command()
@click.argument("args", nargs=-1, required=True)
@click.option("-o", "--output", default=None, help="Output directory (default: <repo>).")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON.")
@click.option("--max-files", type=int, default=50, help="Max source files to scan (default: 50).")
@_llm_options
def codemap(args: tuple[str, ...], output: str | None, json_mode: bool,
            max_files: int, provider: str, model_tier: str, model_id: str | None,
            api_key: str | None, workspace: str | None) -> None:
    """Generate an architecture codemap via LLM inference.

    \b
    Examples:
      dw local codemap org/repo "Map the public API surface"
      dw local codemap --workspace ./myproject "trace the CLI dispatch"
      dw local codemap org/repo "Auth flow" -m k2.6 -p go
    """
    if len(args) >= 2:
        org, repo = _parse_repo(args[0])
        query_text = " ".join(args[1:])
    elif len(args) == 1 and workspace:
        org, repo = "local", os.path.basename(os.path.abspath(workspace))
        query_text = args[0]
    else:
        raise click.UsageError(
            "Usage: dw local codemap org/repo 'query'  OR  dw local codemap -w ./dir 'query'"
        )

    vault_dir = output or repo
    workspace_path = _resolve_workspace(workspace, org, repo)
    client = _make_client(provider, model_tier, model_id, api_key)

    click.echo(f"Generating codemap ({client.provider}/{client.model})...")
    click.echo(f"  Query: {query_text}")
    click.echo(f"  Max files: {max_files}", nl=True)

    try:
        artifact = _generate_map(
            workspace=Path(workspace_path),
            prompt=query_text,
            client=client,
            max_files=max_files,
        )
    except Exception as exc:
        raise click.ClickException(str(exc))

    n_traces = len(artifact.traces)
    n_locs = sum(len(t.locations) for t in artifact.traces)
    click.echo(f"  Result: {n_traces} traces, {n_locs} locations, mermaid={'yes' if artifact.mermaidDiagram else 'no'}")

    if json_mode:
        click.echo(_json.dumps(artifact.to_dict(), indent=2))
        return

    os.makedirs(vault_dir, exist_ok=True)
    has_source = _setup_source_symlink(org, repo, vault_dir, workspace_path)

    lat_dir = os.path.join(vault_dir, "lat.md")
    cm_dir = os.path.join(lat_dir, "codemaps")
    os.makedirs(cm_dir, exist_ok=True)

    slug = _sanitize_stem(artifact.title or query_text[:60])
    md_content = _codemap_to_markdown(artifact, org, repo, query_text, has_source, workspace_path)

    filepath = os.path.join(cm_dir, f"{slug}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)
    click.echo(f"\n  Written: lat.md/codemaps/{slug}.md ({len(md_content):,} chars)")

    _update_lat_index(lat_dir, "Codemaps", "Architecture traces generated via local LLM inference.", f"codemaps/{slug}")
    click.echo(f"\nDone: codemap → {filepath}")


# ---------------------------------------------------------------------------
# Subcommand: lookup
# ---------------------------------------------------------------------------

@local.command()
@click.argument("args", nargs=-1)
@click.option("-o", "--output", default=None, help="Output directory (default: <repo>).")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON.")
@click.option("--symbols", is_flag=True, help="List all symbols instead of documenting one.")
@_llm_options
def lookup(args: tuple[str, ...], output: str | None, json_mode: bool,
           symbols: bool, provider: str, model_tier: str, model_id: str | None,
           api_key: str | None, workspace: str | None) -> None:
    """Generate symbol documentation via LLM inference.

    \b
    Examples:
      dw local lookup org/repo createRouter
      dw local lookup --workspace ./myproject myFunction
      dw local lookup --workspace . --symbols
    """
    symbol_name: str | None = None
    if len(args) >= 2:
        org, repo = _parse_repo(args[0])
        symbol_name = args[1]
    elif len(args) == 1:
        if workspace:
            org, repo = "local", os.path.basename(os.path.abspath(workspace))
            symbol_name = args[0]
        elif "/" in args[0]:
            org, repo = _parse_repo(args[0])
        else:
            raise click.UsageError("Provide repo (org/repo) or --workspace.")
    elif workspace:
        org, repo = "local", os.path.basename(os.path.abspath(workspace))
    else:
        raise click.UsageError(
            "Usage: dw local lookup org/repo [symbol]  OR  dw local lookup -w ./dir [symbol]"
        )

    vault_dir = output or repo
    workspace_path = _resolve_workspace(workspace, org, repo)

    if symbols:
        click.echo(f"Scanning symbols in {org}/{repo}...")
        syms = _list_symbols(Path(workspace_path), max_files=200)
        if not syms:
            raise click.ClickException("No symbols found.")
        by_file: dict[str, list[tuple[str, int]]] = {}
        for name, path, line in syms:
            by_file.setdefault(path, []).append((name, line))
        for path in sorted(by_file):
            click.echo(f"\n  {path}:")
            for name, line in by_file[path]:
                click.echo(f"    {line:4d}  {name}")
        click.echo(f"\n  Total: {len(syms)} symbols in {len(by_file)} files")
        return

    if not symbol_name:
        raise click.UsageError("Provide a symbol name or use --symbols to list all.")

    client = _make_client(provider, model_tier, model_id, api_key)
    click.echo(f"Looking up '{symbol_name}' in {org}/{repo} ({client.provider}/{client.model})...")

    try:
        article = _generate_lookup(Path(workspace_path), symbol_name, client)
    except Exception as exc:
        raise click.ClickException(str(exc))

    if json_mode:
        click.echo(_json.dumps({"symbol": symbol_name, "repo": f"{org}/{repo}", "article": article}))
        return

    os.makedirs(vault_dir, exist_ok=True)
    _setup_source_symlink(org, repo, vault_dir, workspace_path)

    lat_dir = os.path.join(vault_dir, "lat.md")
    sym_dir = os.path.join(lat_dir, "symbols")
    os.makedirs(sym_dir, exist_ok=True)

    slug = _sanitize_stem(symbol_name)
    filepath = os.path.join(sym_dir, f"{slug}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(article)
    click.echo(f"\n  Written: lat.md/symbols/{slug}.md ({len(article):,} chars)")

    _update_lat_index(lat_dir, "Symbols", "Symbol documentation generated via local LLM inference.", f"symbols/{slug}")
    click.echo(f"\nDone: lookup → {filepath}")
