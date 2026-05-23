"""`cli-web-deepwiki normalize` — canonicalize Markdown via remark/OFM."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from ..utils.helpers import emit, handle_errors
from ..utils.unified_bridge import UnifiedBridge


@click.command("normalize")
@click.argument("md_path", metavar="MD_PATH")
@click.option(
    "--ofm/--no-ofm",
    default=True,
    show_default=True,
    help="Apply Obsidian-flavored Markdown rules (wikilinks, callouts).",
)
@click.option(
    "--inplace",
    is_flag=True,
    default=False,
    help="Write canonical output back to MD_PATH.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def normalize(
    ctx: click.Context,
    md_path: str,
    ofm: bool,
    inplace: bool,
    json_flag: bool,
) -> None:
    """Normalize a Markdown file via remark + OFM canonical formatting.

    MD_PATH may be '-' for stdin (in which case --inplace is rejected).
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        if md_path == "-":
            if inplace:
                raise click.BadParameter("--inplace cannot be combined with stdin input.")
            source_text = sys.stdin.read()
            target_path: Path | None = None
        else:
            target_path = Path(md_path)
            if not target_path.is_file():
                raise click.BadParameter(f"Markdown file not found: {md_path}")
            source_text = target_path.read_text(encoding="utf-8")

        options = {"ofm": ofm}
        with UnifiedBridge() as bridge:
            result = bridge.md_to_ofm(source_text, options=options)
        normalized = result.get("markdown", "")

        if inplace and target_path is not None:
            target_path.write_text(normalized, encoding="utf-8")
            payload = {
                "path": str(target_path),
                "bytes_written": len(normalized.encode("utf-8")),
                "ofm": ofm,
            }
            emit(payload, json_mode=json_mode)
            return

        if json_mode:
            emit({"markdown": normalized, "ofm": ofm}, json_mode=True)
        else:
            click.echo(normalized)
