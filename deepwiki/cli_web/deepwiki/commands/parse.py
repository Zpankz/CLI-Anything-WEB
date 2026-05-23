"""`cli-web-deepwiki parse` — convert HTML to AST or Markdown."""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import click
import httpx

from ..utils.helpers import emit, handle_errors
from ..utils.output import console
from ..utils.unified_bridge import UnifiedBridge


_TARGETS = ["hast", "mdast", "nlcst", "markdown"]


def _read_input(arg: str) -> tuple[str, str | None]:
    """Resolve the input argument to (html_or_md, base_url).

    Accepts a URL, file path, or '-' (stdin).
    """
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
    # Treat the literal arg as raw HTML.
    return s, None


@click.command("parse")
@click.argument("source", metavar="HTML_OR_URL")
@click.option(
    "--target",
    type=click.Choice(_TARGETS, case_sensitive=False),
    default="mdast",
    show_default=True,
    help="Output format for the parsed input.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def parse(
    ctx: click.Context,
    source: str,
    target: str,
    json_flag: bool,
) -> None:
    """Parse HTML to a syntax tree (hast, mdast, nlcst) or Markdown.

    SOURCE may be a URL, a path to an HTML file, '-' for stdin, or raw HTML.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        html, base_url = _read_input(source)
        target_lower = target.lower()

        with UnifiedBridge() as bridge:
            if target_lower == "markdown":
                result = bridge.html_to_md(html, base_url=base_url)
                payload = {"markdown": result.get("markdown", "")}
                if json_mode:
                    click.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    click.echo(payload["markdown"])
                return
            if target_lower == "hast":
                result = bridge.ast_convert(input=html, frm="html", to="hast")
                tree = result.get("output", result)
            elif target_lower == "mdast":
                result = bridge.html_to_mdast(html)
                tree = result.get("tree", result)
            elif target_lower == "nlcst":
                md_result = bridge.html_to_md(html, base_url=base_url)
                markdown = md_result.get("markdown", "")
                nlcst_result = bridge.md_to_nlcst(markdown)
                tree = nlcst_result.get("tree", nlcst_result)
            else:  # pragma: no cover — guarded by Choice
                raise click.BadParameter(f"Unsupported target: {target}")

        if json_mode:
            click.echo(_json.dumps(tree, ensure_ascii=False, indent=2, default=str))
        else:
            console().print_json(data=tree, default=str)
