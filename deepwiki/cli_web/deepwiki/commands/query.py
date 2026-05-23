"""`cli-web-deepwiki query` — run unist-util-select queries against an AST."""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import click

from ..utils.helpers import emit, handle_errors
from ..utils.output import console
from ..utils.unified_bridge import UnifiedBridge


_TYPES = ["mdast", "hast", "nlcst"]


def _build_tree(bridge: UnifiedBridge, source: str, tree_type: str) -> dict:
    """Convert source text to the requested AST type using the bridge."""
    if tree_type == "mdast":
        result = bridge.ast_convert(input=source, frm="md", to="mdast")
    elif tree_type == "hast":
        result = bridge.ast_convert(input=source, frm="html", to="hast")
    elif tree_type == "nlcst":
        result = bridge.md_to_nlcst(source)
        return result.get("tree", result)
    else:  # pragma: no cover — guarded by Choice
        raise click.BadParameter(f"Unsupported tree type: {tree_type}")
    return result.get("output", result.get("tree", result))


@click.command("query")
@click.argument("md_path", metavar="MD_PATH")
@click.option(
    "--select",
    "selector",
    required=True,
    help="unist-util-select selector (e.g. 'heading', 'link', 'code', 'inlineCode', 'table').",
)
@click.option(
    "--type",
    "tree_type",
    type=click.Choice(_TYPES, case_sensitive=False),
    default="mdast",
    show_default=True,
    help="AST type to query against.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def query(
    ctx: click.Context,
    md_path: str,
    selector: str,
    tree_type: str,
    json_flag: bool,
) -> None:
    """Query an AST with a unist-util-select selector.

    MD_PATH may be '-' for stdin. The input is converted to the requested AST type
    (mdast/hast/nlcst) before the selector is applied. Output is the list of
    matching nodes.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        if md_path == "-":
            source_text = sys.stdin.read()
        else:
            p = Path(md_path)
            if not p.is_file():
                raise click.BadParameter(f"File not found: {md_path}")
            source_text = p.read_text(encoding="utf-8")

        with UnifiedBridge() as bridge:
            tree = _build_tree(bridge, source_text, tree_type.lower())
            result = bridge.ast_query(tree, type=tree_type.lower(), selector=selector)

        matches = result.get("matches", []) if isinstance(result, dict) else result
        payload = {"selector": selector, "type": tree_type.lower(), "count": len(matches), "matches": matches}

        if json_mode:
            click.echo(_json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            console().print(f"[cyan]selector:[/cyan] {selector}  [cyan]type:[/cyan] {tree_type}  "
                            f"[cyan]matches:[/cyan] {len(matches)}")
            console().print_json(data=matches, default=str)
