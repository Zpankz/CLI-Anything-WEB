"""`cli-web-deepwiki convert` — round-trip between HTML/MD/AST/XML/NLCST."""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import click

from ..utils.helpers import emit, handle_errors
from ..utils.unified_bridge import UnifiedBridge


_FORMATS = ["html", "markdown", "md", "mdast", "hast", "nlcst", "xast", "xml"]
_FORMAT_ALIASES = {"markdown": "md"}


def _normalize_fmt(fmt: str) -> str:
    fmt = fmt.lower()
    return _FORMAT_ALIASES.get(fmt, fmt)


@click.command("convert")
@click.argument("source", metavar="INPUT")
@click.option(
    "--from",
    "src_fmt",
    type=click.Choice(_FORMATS, case_sensitive=False),
    required=True,
    help="Input format.",
)
@click.option(
    "--to",
    "dst_fmt",
    type=click.Choice(_FORMATS, case_sensitive=False),
    required=True,
    help="Output format.",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write output to PATH instead of stdout.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def convert(
    ctx: click.Context,
    source: str,
    src_fmt: str,
    dst_fmt: str,
    out_path: str | None,
    json_flag: bool,
) -> None:
    """Convert between formats: html, md, mdast, hast, nlcst, xast, xml.

    SOURCE may be a path to a file or '-' for stdin.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        if source == "-":
            input_text = sys.stdin.read()
        else:
            p = Path(source)
            if p.is_file():
                input_text = p.read_text(encoding="utf-8")
            else:
                input_text = source  # treat as raw

        frm = _normalize_fmt(src_fmt)
        to = _normalize_fmt(dst_fmt)

        with UnifiedBridge() as bridge:
            result = bridge.ast_convert(input=input_text, frm=frm, to=to)
        output = result.get("output", result) if isinstance(result, dict) else result

        if isinstance(output, (dict, list)):
            rendered = _json.dumps(output, ensure_ascii=False, indent=2, default=str)
        else:
            rendered = str(output)

        if out_path:
            Path(out_path).write_text(rendered, encoding="utf-8")
            emit(
                {"from": frm, "to": to, "out": out_path, "bytes": len(rendered.encode("utf-8"))},
                json_mode=json_mode,
            )
            return

        if json_mode:
            click.echo(_json.dumps(
                {"from": frm, "to": to, "output": output},
                ensure_ascii=False,
                indent=2,
                default=str,
            ))
        else:
            click.echo(rendered)
