"""`cli-web-deepwiki analyze` — readability/stats/entities for Markdown."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from ..utils.helpers import emit, handle_errors
from ..utils.output import console
from ..utils.unified_bridge import UnifiedBridge


_METRICS = ["readability", "stats", "entities", "all"]


@click.command("analyze")
@click.argument("source", metavar="MD_OR_PATH")
@click.option(
    "--metrics",
    type=click.Choice(_METRICS, case_sensitive=False),
    default="all",
    show_default=True,
    help="Which metric family to report.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def analyze(
    ctx: click.Context,
    source: str,
    metrics: str,
    json_flag: bool,
) -> None:
    """Analyze a Markdown document via retext: readability, stats, and entities.

    SOURCE may be a path to a Markdown file, '-' for stdin, or raw Markdown.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        if source == "-":
            text = sys.stdin.read()
        else:
            p = Path(source)
            if p.is_file():
                text = p.read_text(encoding="utf-8")
            else:
                text = source

        with UnifiedBridge() as bridge:
            result = bridge.analyze(text)

        m = metrics.lower()
        if m != "all" and isinstance(result, dict):
            filtered = {k: v for k, v in result.items() if k.lower() == m}
            payload = filtered or {m: result.get(m)}
        else:
            payload = result or {}

        def _render(_data) -> None:
            from rich.table import Table

            stats = payload.get("stats") if isinstance(payload, dict) else None
            readability = payload.get("readability") if isinstance(payload, dict) else None
            entities = payload.get("entities") if isinstance(payload, dict) else None

            if stats:
                t = Table(title="Statistics")
                t.add_column("Metric", style="cyan")
                t.add_column("Value", justify="right", style="yellow")
                for k, v in (stats or {}).items():
                    t.add_row(str(k), str(v))
                console().print(t)
            if readability:
                t = Table(title="Readability")
                t.add_column("Score", style="cyan")
                t.add_column("Value", justify="right", style="yellow")
                for k, v in (readability or {}).items():
                    t.add_row(str(k), str(v))
                console().print(t)
            if entities:
                t = Table(title="Entities")
                t.add_column("Type", style="cyan")
                t.add_column("Text", style="white")
                if isinstance(entities, list):
                    for ent in entities:
                        t.add_row(str(ent.get("type", "?")), str(ent.get("text", ent)))
                else:
                    for k, v in (entities or {}).items():
                        t.add_row(str(k), str(v))
                console().print(t)
            if not (stats or readability or entities):
                console().print_json(data=payload, default=str)

        emit(payload, json_mode=json_mode, table_renderer=_render)
