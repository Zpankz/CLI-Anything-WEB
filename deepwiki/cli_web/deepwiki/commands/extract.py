"""`cli-web-deepwiki extract` — defuddle any HTML page into clean Markdown."""
from __future__ import annotations

import sys
from pathlib import Path

import click
import httpx

from ..utils.helpers import emit, handle_errors
from ..utils.unified_bridge import UnifiedBridge


def _read_source(arg: str) -> tuple[str, str | None]:
    """Resolve a URL / path / '-' (stdin) / raw HTML to (html, base_url)."""
    s = arg.strip()
    if s == "-":
        return sys.stdin.read(), None
    if s.startswith(("http://", "https://")):
        resp = httpx.get(
            s,
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "cli-web-deepwiki/0.1.0"},
        )
        resp.raise_for_status()
        return resp.text, s
    p = Path(s)
    if p.is_file():
        return p.read_text(encoding="utf-8"), None
    return s, None


@click.command("extract")
@click.argument("source", metavar="URL_OR_PATH")
@click.option(
    "--readability",
    is_flag=True,
    default=False,
    help="Use Readability extraction mode (defuddle fallback).",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write extracted Markdown to PATH.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def extract(
    ctx: click.Context,
    source: str,
    readability: bool,
    out_path: str | None,
    json_flag: bool,
) -> None:
    """Extract clean Markdown from any HTML page using defuddle.

    SOURCE may be a URL, a local HTML file, '-' for stdin, or raw HTML.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        html, base_url = _read_source(source)
        with UnifiedBridge() as bridge:
            params = {"html": html, "baseUrl": base_url}
            if readability:
                params["options"] = {"readability": True}
            result = bridge.call("htmlToMd", params)

        markdown = result.get("markdown", "") if isinstance(result, dict) else str(result)
        title = (result.get("title") if isinstance(result, dict) else None) or ""
        metadata = result.get("metadata") if isinstance(result, dict) else {}

        payload = {
            "title": title,
            "markdown": markdown,
            "metadata": metadata or {},
            "source": source,
        }

        if out_path:
            Path(out_path).write_text(markdown, encoding="utf-8")
            payload["out"] = out_path
            payload["bytes"] = len(markdown.encode("utf-8"))
            emit(payload, json_mode=json_mode)
            return

        if json_mode:
            emit(payload, json_mode=True)
        else:
            click.echo(markdown)
