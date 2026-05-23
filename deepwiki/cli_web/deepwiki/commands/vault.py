"""`cli-web-deepwiki vault` — generate a full Obsidian vault for a repo."""
from __future__ import annotations

import json as _json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from ..core.client import DeepwikiClient
from ..core.models import Page, WikiTree
from ..utils.helpers import emit, handle_errors, parse_repo
from ..utils.output import console, info, success, warn
from ..utils.unified_bridge import UnifiedBridge


_SECTION_RE = re.compile(r"^(\d+)(?:\.\d+)*-(.+)$")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_ctx(
    page: Page,
    *,
    indexed_at: str | None,
    indexed_commit: str | None,
    topics: list[str] | None = None,
    aliases: list[str] | None = None,
) -> dict:
    """Construct the per-page context passed to vaultPage().

    Adds rich Obsidian-friendly fields:
      - aliases: slug variants (with original colons / parens) so [[orig]] resolves
      - tags:    repo topics + stable per-vault marker tags
      - section: numeric prefix grouping key for Dataview filtering
    """
    sec = _section_for_slug(page.slug)
    return {
        "repo": page.repo,
        "slug": page.slug,
        "title": page.title,
        "url": page.url,
        "deepwiki_url": page.url,
        "indexed_at": indexed_at,
        "indexed_commit": indexed_commit,
        "fetched_at": _now_iso(),
        "aliases": aliases or _slug_aliases(page.slug, page.title),
        "tags": _vault_tags(topics or []),
        "section": sec,
    }


def _slug_aliases(slug: str, title: str) -> list[str]:
    """Aliases let Obsidian resolve `[[Original Title]]` and the raw slug.

    Example: vault filename `7.2-reduce-knowledge-extraction.md` exposes
    aliases `["7.2-reduce:-knowledge-extraction", "Reduce: Knowledge Extraction"]`.
    """
    out: list[str] = []
    if slug:
        out.append(slug)
    if title and title != slug:
        out.append(title)
    seen: set[str] = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def _vault_tags(topics: list[str]) -> list[str]:
    """Build Obsidian tags (no leading #, normalized)."""
    base = ["deepwiki", "generated"]
    out = list(base)
    for t in topics:
        if isinstance(t, str) and t.strip():
            tag = re.sub(r"[^a-z0-9-]+", "-", t.lower()).strip("-")
            if tag and tag not in out:
                out.append(tag)
    return out


# ── Backlinks pass ────────────────────────────────────────────────────────────


def _strip_code(text: str) -> str:
    """Remove fenced + inline code so they don't pollute backlink scanning."""
    text = _FENCED_CODE.sub("", text)
    text = _INLINE_CODE.sub("", text)
    return text


def _scan_outgoing_links(md_text: str) -> set[str]:
    """Return the set of [[target]] slugs (without alias) referenced in `md_text`.

    Skips anything inside fenced or inline code (those are illustrations, not
    real cross-references).
    """
    body = _strip_code(md_text)
    return {m.group(1).strip() for m in _WIKILINK_RE.finditer(body)}


def _split_frontmatter(content: str) -> tuple[str | None, str]:
    """Return (frontmatter_block_including_delimiters, body) or (None, content)."""
    if not content.startswith("---\n"):
        return None, content
    end = content.find("\n---\n", 4)
    if end == -1:
        return None, content
    return content[: end + 5], content[end + 5 :]


def _apply_backlinks_pass(out: Path) -> int:
    """Append a `## Backlinks` section to every page that's referenced.

    Returns the number of pages that received backlinks.
    """
    md_files = sorted(out.glob("*.md"))
    if not md_files:
        return 0
    # Map filename stems → titles for nicer display in the backlinks list
    titles: dict[str, str] = {}
    bodies: dict[str, str] = {}
    for p in md_files:
        text = p.read_text(encoding="utf-8")
        bodies[p.stem] = text
        # Pull title from frontmatter if present
        fm, _ = _split_frontmatter(text)
        title_match = re.search(r"^title:\s*(.+)$", fm or "", re.MULTILINE)
        if title_match:
            titles[p.stem] = title_match.group(1).strip().strip('"').strip("'")
        else:
            titles[p.stem] = p.stem

    # Build forward index (using safe_filename to map raw slugs to actual filenames)
    from ..utils.helpers import safe_filename
    forward: dict[str, set[str]] = {stem: set() for stem in bodies}
    for stem, body in bodies.items():
        for raw_target in _scan_outgoing_links(body):
            normalized = safe_filename(raw_target)
            if normalized in bodies and normalized != stem:
                forward[stem].add(normalized)

    # Invert to backward index
    backward: dict[str, list[str]] = {stem: [] for stem in bodies}
    for src, targets in forward.items():
        for tgt in targets:
            backward[tgt].append(src)

    # Append "## Backlinks" sections (sorted, deterministic)
    pages_with_backlinks = 0
    for stem, refs in backward.items():
        if not refs:
            continue
        refs = sorted(set(refs))
        path = out / f"{stem}.md"
        body = bodies[stem]
        # Strip any pre-existing backlinks block (idempotent re-run)
        body = re.sub(
            r"\n+## Backlinks\n.*?(?=\n## |\Z)",
            "",
            body,
            flags=re.DOTALL,
        )
        block = "\n\n## Backlinks\n\n" + "\n".join(
            f"- [[{r}|{titles.get(r, r)}]]" for r in refs
        ) + "\n"
        path.write_text(body.rstrip() + block, encoding="utf-8")
        pages_with_backlinks += 1
    return pages_with_backlinks


# ── Description extraction (for frontmatter) ──────────────────────────────────


def _first_paragraph(md_body: str, max_chars: int = 220) -> str:
    """Pluck the first non-empty prose paragraph for frontmatter description."""
    body = _strip_code(md_body)
    # Drop leading blank lines, headings, and list/code lines
    paragraphs = re.split(r"\n\s*\n", body)
    for para in paragraphs:
        text = para.strip()
        if not text or text.startswith(("#", "-", "*", "|", ">", "```")):
            continue
        # Strip wikilink/markdown link decoration
        text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", lambda m: m.group(1), text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 30:
            return text[:max_chars] + ("…" if len(text) > max_chars else "")
    return ""


def _enrich_frontmatter(out: Path) -> int:
    """Add `description:` and (where missing) `aliases:` to every page.

    Returns the number of pages updated.
    """
    n = 0
    for p in sorted(out.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(text)
        if not fm:
            continue
        if re.search(r"^description:", fm, re.MULTILINE):
            continue  # already enriched
        desc = _first_paragraph(body)
        if not desc:
            continue
        # Quote-safe YAML — escape double quotes
        safe_desc = desc.replace('\\', '\\\\').replace('"', '\\"')
        new_fm = fm.rstrip("\n").rstrip("---").rstrip() + f'\ndescription: "{safe_desc}"\n---\n'
        p.write_text(new_fm + body, encoding="utf-8")
        n += 1
    return n


def _section_for_slug(slug: str) -> str | None:
    """Return the top-level section slug for a sub-section (e.g. '3.1-x' → '3-x'?).

    The actual top-level slug isn't derivable from the prefix alone, so we expose
    only the leading numeric prefix as a grouping key.
    """
    m = _SECTION_RE.match(slug)
    return m.group(1) if m else None


def _structure_from_tree(tree: WikiTree) -> list[dict[str, Any]]:
    """Group pages by leading numeric section to feed vault_moc().

    A page with slug `^N-...` (no `.` in the prefix) is treated as the section
    landing page; its title becomes the section title.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    top_level: dict[str, str] = {}
    for p in tree.pages:
        m = _SECTION_RE.match(p.slug)
        if not m:
            continue
        section = m.group(1)
        if section not in groups:
            groups[section] = []
            order.append(section)
        groups[section].append({"slug": p.slug, "title": p.title})
        # The slug `<section>-...` with no decimal (e.g. "3-core-concepts")
        # is the section's landing page.
        if p.slug.startswith(f"{section}-"):
            top_level.setdefault(section, p.title)
    out: list[dict[str, Any]] = []
    for section in order:
        out.append({
            "section": section,
            "title": top_level.get(section) or section,
            "pages": groups[section],
        })
    return out


def _process_page(
    bridge: UnifiedBridge,
    bridge_lock: threading.Lock,
    client: DeepwikiClient,
    page: Page,
    *,
    indexed_at: str | None,
    indexed_commit: str | None,
    frontmatter: bool,
    topics: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch + transform one page. Bridge calls are serialized via lock."""
    pg = client.fetch_page(page.repo, page.slug)
    ctx = _build_ctx(
        pg,
        indexed_at=indexed_at,
        indexed_commit=indexed_commit,
        topics=topics,
    )
    with bridge_lock:
        result = bridge.vault_page(pg.html or "", ctx=ctx)
    md = result.get("markdown", "")
    fm = result.get("frontmatter") or {}
    links = result.get("links") or []
    return {
        "slug": pg.slug,
        "title": pg.title,
        "markdown": md,
        "frontmatter": fm if frontmatter else {},
        "links": links,
        "ctx": ctx,
    }


def _write_page_file(out_dir: Path, slug: str, markdown: str) -> Path:
    """Write `<out>/<slug>.md` using the shared `safe_filename` helper.

    Critical: the SAME helper is used by the wikilink rewriter and MOC
    builder downstream so filenames, wikilinks, and the MOC index all agree.
    Parens are preserved (Obsidian-safe); colons / pipes / quotes are stripped.
    """
    from ..utils.helpers import safe_filename
    safe = safe_filename(slug) or "page"
    target = out_dir / f"{safe}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


def _write_obsidian_config(out_dir: Path) -> None:
    """Write `.obsidian/app.json` so [[wikilinks]] resolve via shortest path."""
    cfg_dir = out_dir / ".obsidian"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "app.json").write_text(
        _json.dumps({"newLinkFormat": "shortest"}, indent=2),
        encoding="utf-8",
    )


@click.command("vault")
@click.argument("repo_arg", metavar="OWNER/REPO")
@click.option(
    "--output",
    "-o",
    "out_dir",
    type=click.Path(file_okay=False, writable=True),
    required=True,
    help="Output directory for the generated vault.",
)
@click.option(
    "--canvas/--no-canvas",
    default=False,
    show_default=True,
    help="Emit `_graph.canvas` JSON Canvas backlink graph.",
)
@click.option(
    "--mocs/--no-mocs",
    default=True,
    show_default=True,
    help="Emit Maps of Content (top-level index.md plus per-section MOCs).",
)
@click.option(
    "--frontmatter/--no-frontmatter",
    default=True,
    show_default=True,
    help="Embed YAML frontmatter on each page.",
)
@click.option(
    "--backlinks/--no-backlinks",
    default=True,
    show_default=True,
    help="Append a `## Backlinks` section to every page that's referenced.",
)
@click.option(
    "--enrich/--no-enrich",
    default=True,
    show_default=True,
    help="Add `description:` (first paragraph) to frontmatter.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process only the first N pages (debug).",
)
@click.option(
    "--concurrent",
    type=int,
    default=4,
    show_default=True,
    help="Parallel HTTP fetches (bridge calls remain serialized).",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def vault(
    ctx: click.Context,
    repo_arg: str,
    out_dir: str,
    canvas: bool,
    mocs: bool,
    frontmatter: bool,
    backlinks: bool,
    enrich: bool,
    limit: int | None,
    concurrent: int,
    json_flag: bool,
) -> None:
    """Generate an Obsidian vault from a DeepWiki repo.

    Each wiki page becomes a Markdown file with YAML frontmatter and rewritten
    `[[wikilinks]]`. Maps of Content (MOCs) and an optional JSON Canvas backlink
    graph round out the vault.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        repo = parse_repo(repo_arg)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        with DeepwikiClient() as client:
            tree = client.wiki_tree(repo)
            overview = client.repo_overview(repo)
            indexed_at = overview.last_indexed
            indexed_commit = overview.indexed_commit

            # Pull topics from the Index for tag enrichment
            topics: list[str] = []
            try:
                idx = client.get_index(repo)
                if idx and idx.topics:
                    topics = list(idx.topics)
            except Exception:
                pass

            pages = list(tree.pages)
            if limit and limit > 0:
                pages = pages[:limit]

            if not pages:
                if not json_mode:
                    warn(f"No pages found for {repo}")
                emit({"pages_written": 0, "output": str(out)}, json_mode=json_mode)
                return

            if not json_mode:
                info(f"Generating vault for {repo} → {out}  ({len(pages)} pages)")

            bridge_lock = threading.Lock()
            results: list[dict[str, Any]] = []

            with UnifiedBridge() as bridge:
                workers = max(1, min(concurrent, 16))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = {
                        pool.submit(
                            _process_page,
                            bridge,
                            bridge_lock,
                            client,
                            p,
                            indexed_at=indexed_at,
                            indexed_commit=indexed_commit,
                            topics=topics,
                            frontmatter=frontmatter,
                        ): p
                        for p in pages
                    }
                    for fut in as_completed(futs):
                        page = futs[fut]
                        try:
                            results.append(fut.result())
                            if not json_mode:
                                console().print(f"[dim]✓ {page.slug}[/dim]")
                        except Exception as exc:  # pragma: no cover
                            if not json_mode:
                                warn(f"failed to process {page.slug}: {exc}")

                # Sort results back to the natural TOC order.
                slug_order = {p.slug: i for i, p in enumerate(pages)}
                results.sort(key=lambda r: slug_order.get(r["slug"], 1_000_000))

                pages_written = 0
                for r in results:
                    _write_page_file(out, r["slug"], r["markdown"])
                    pages_written += 1

                mocs_written = 0
                if mocs and results:
                    moc_pages = [{"slug": r["slug"], "title": r["title"]} for r in results]
                    structure = _structure_from_tree(tree)
                    with bridge_lock:
                        moc_result = bridge.vault_moc(
                            repo=repo,
                            pages=moc_pages,
                            structure=structure,
                        )
                    if isinstance(moc_result, dict):
                        index_md = moc_result.get("markdown") or moc_result.get("index")
                        if index_md:
                            (out / "index.md").write_text(index_md, encoding="utf-8")
                            mocs_written += 1
                        sections = moc_result.get("sections") or []
                        for sec in sections:
                            sec_dir = out / str(sec.get("slug") or sec.get("section") or "section")
                            sec_dir.mkdir(parents=True, exist_ok=True)
                            md = sec.get("markdown") or ""
                            (sec_dir / "_index.md").write_text(md, encoding="utf-8")
                            mocs_written += 1

                canvas_written = 0
                if canvas and results:
                    canvas_pages = [{"slug": r["slug"], "title": r["title"]} for r in results]
                    canvas_links: list[dict] = []
                    for r in results:
                        for link in r.get("links") or []:
                            if isinstance(link, dict):
                                canvas_links.append({"from": r["slug"], **link})
                    with bridge_lock:
                        canvas_result = bridge.vault_canvas(
                            repo=repo,
                            pages=canvas_pages,
                            links=canvas_links,
                        )
                    canvas_data = (
                        canvas_result.get("canvas")
                        if isinstance(canvas_result, dict)
                        else canvas_result
                    )
                    canvas_text = (
                        canvas_data
                        if isinstance(canvas_data, str)
                        else _json.dumps(canvas_data, ensure_ascii=False, indent=2)
                    )
                    (out / "_graph.canvas").write_text(canvas_text, encoding="utf-8")
                    canvas_written = 1

            _write_obsidian_config(out)

        # Post-passes (operate on what's already on disk; pure Python)
        backlinks_added = 0
        if backlinks:
            backlinks_added = _apply_backlinks_pass(out)

        descriptions_added = 0
        if enrich:
            descriptions_added = _enrich_frontmatter(out)

        summary = {
            "repo": repo,
            "output": str(out),
            "pages_written": pages_written,
            "mocs_written": mocs_written,
            "canvas_written": canvas_written,
            "backlinks_added": backlinks_added,
            "descriptions_added": descriptions_added,
        }

        def _render(_data) -> None:
            success(f"Vault written: {out}")
            console().print(
                f"  pages: [yellow]{pages_written}[/yellow]  "
                f"mocs: [yellow]{mocs_written}[/yellow]  "
                f"canvas: [yellow]{canvas_written}[/yellow]  "
                f"backlinks: [yellow]{backlinks_added}[/yellow]  "
                f"descriptions: [yellow]{descriptions_added}[/yellow]"
            )

        emit(summary, json_mode=json_mode, table_renderer=_render)
