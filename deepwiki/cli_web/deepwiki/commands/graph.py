"""`cli-web-deepwiki graph` — emit the wiki structure as a graph (mermaid/canvas/dot/json)."""
from __future__ import annotations

import json as _json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

import click

from ..core.client import DeepwikiClient
from ..core.models import Page, WikiTree
from ..utils.helpers import emit, handle_errors, parse_repo
from ..utils.unified_bridge import UnifiedBridge


_FORMATS = ["mermaid", "canvas", "json", "dot"]


def _safe_id(slug: str) -> str:
    """Mermaid/DOT-safe node id."""
    return "n_" + re.sub(r"[^A-Za-z0-9_]+", "_", slug).strip("_")


def _extract_links_from_mdast(tree: Any, repo: str, valid_slugs: set[str]) -> list[str]:
    """Walk an mdast tree and collect /repo/slug-style internal links."""
    out: list[str] = []
    prefix = f"/{repo}/"

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "link":
                url = str(node.get("url", "") or "")
                slug: str | None = None
                if url.startswith(prefix):
                    slug = url[len(prefix):].split("#", 1)[0].split("?", 1)[0].strip("/")
                elif url.startswith("https://deepwiki.com" + prefix):
                    slug = url[len("https://deepwiki.com" + prefix):].split("#", 1)[0].split("?", 1)[0].strip("/")
                if slug and slug in valid_slugs:
                    out.append(slug)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(tree)
    return out


def _fetch_links(
    bridge: UnifiedBridge,
    bridge_lock: threading.Lock,
    client: DeepwikiClient,
    page: Page,
    valid_slugs: set[str],
) -> tuple[str, list[str]]:
    pg = client.fetch_page(page.repo, page.slug)
    with bridge_lock:
        result = bridge.html_to_mdast(pg.html or "")
    tree = result.get("tree", result)
    links = _extract_links_from_mdast(tree, page.repo, valid_slugs)
    return page.slug, list(dict.fromkeys(links))


def _emit_mermaid(nodes: list[dict], edges: list[dict]) -> str:
    lines = ["graph TD"]
    for n in nodes:
        nid = _safe_id(n["slug"])
        label = n["title"].replace('"', "'")
        lines.append(f'    {nid}["{label}"]')
    for e in edges:
        a = _safe_id(e["from"])
        b = _safe_id(e["to"])
        lines.append(f"    {a} --> {b}")
    return "\n".join(lines)


def _emit_dot(nodes: list[dict], edges: list[dict]) -> str:
    out = ["digraph G {", "  rankdir=LR;", "  node [shape=box, fontname=\"Helvetica\"];"]
    for n in nodes:
        nid = _safe_id(n["slug"])
        label = n["title"].replace('"', "'")
        out.append(f'  {nid} [label="{label}"];')
    for e in edges:
        out.append(f'  {_safe_id(e["from"])} -> {_safe_id(e["to"])};')
    out.append("}")
    return "\n".join(out)


def _emit_canvas(nodes: list[dict], edges: list[dict]) -> dict:
    """Minimal JSON Canvas (.canvas) layout — grid placement."""
    canvas_nodes = []
    cols = max(1, int(len(nodes) ** 0.5))
    for i, n in enumerate(nodes):
        row, col = divmod(i, cols)
        canvas_nodes.append({
            "id": n["slug"],
            "type": "text",
            "x": col * 320,
            "y": row * 200,
            "width": 280,
            "height": 120,
            "text": f"# {n['title']}\n\n{n['slug']}",
        })
    canvas_edges = [
        {
            "id": f"{e['from']}->{e['to']}",
            "fromNode": e["from"],
            "fromSide": "right",
            "toNode": e["to"],
            "toSide": "left",
        }
        for e in edges
    ]
    return {"nodes": canvas_nodes, "edges": canvas_edges}


@click.command("graph")
@click.argument("repo_arg", metavar="OWNER/REPO")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(_FORMATS, case_sensitive=False),
    default="mermaid",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write output to PATH.",
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
    help="Parallel HTTP fetches.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON (overrides --format with the json format).",
)
@click.pass_context
def graph(
    ctx: click.Context,
    repo_arg: str,
    fmt: str,
    out_path: str | None,
    limit: int | None,
    concurrent: int,
    json_flag: bool,
) -> None:
    """Build a graph of a repo's wiki: nodes are pages, edges are intra-wiki links.

    Output formats: mermaid (graph TD), canvas (JSON Canvas), dot (Graphviz), json.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        repo = parse_repo(repo_arg)
        with DeepwikiClient() as client:
            tree: WikiTree = client.wiki_tree(repo)
            pages = list(tree.pages)
            if limit and limit > 0:
                pages = pages[:limit]
            valid = {p.slug for p in pages}

            bridge_lock = threading.Lock()
            slug_to_links: dict[str, list[str]] = {}
            with UnifiedBridge() as bridge:
                workers = max(1, min(concurrent, 16))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = {
                        pool.submit(_fetch_links, bridge, bridge_lock, client, p, valid): p
                        for p in pages
                    }
                    for fut in as_completed(futs):
                        try:
                            slug, links = fut.result()
                            slug_to_links[slug] = links
                        except Exception:
                            slug_to_links[futs[fut].slug] = []

        nodes = [{"slug": p.slug, "title": p.title, "url": p.url} for p in pages]
        edges: list[dict] = []
        for src, targets in slug_to_links.items():
            for tgt in targets:
                if src != tgt and tgt in valid:
                    edges.append({"from": src, "to": tgt})

        chosen = "json" if json_mode else fmt.lower()
        if chosen == "mermaid":
            rendered = _emit_mermaid(nodes, edges)
        elif chosen == "dot":
            rendered = _emit_dot(nodes, edges)
        elif chosen == "canvas":
            rendered = _json.dumps(_emit_canvas(nodes, edges), ensure_ascii=False, indent=2)
        else:  # json
            rendered = _json.dumps(
                {"repo": repo, "nodes": nodes, "edges": edges},
                ensure_ascii=False,
                indent=2,
            )

        if out_path:
            Path(out_path).write_text(rendered, encoding="utf-8")
            emit(
                {
                    "repo": repo,
                    "format": chosen,
                    "out": out_path,
                    "nodes": len(nodes),
                    "edges": len(edges),
                },
                json_mode=json_mode,
            )
            return

        if json_mode:
            click.echo(rendered)
        else:
            click.echo(rendered)
