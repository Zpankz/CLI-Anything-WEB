"""`cli-web-deepwiki search` — search public DeepWiki indexes."""
from __future__ import annotations

import click

from ..core.client import DeepwikiClient
from ..core.models import Index
from ..utils.helpers import emit, handle_errors
from ..utils.output import render_index_table


@click.command("search")
@click.argument("query", required=False, default=None)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=25,
    show_default=True,
    help="Maximum number of results to return.",
)
@click.option(
    "--lang",
    "-l",
    type=str,
    default=None,
    help="Filter results by language (case-insensitive substring match).",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def search(
    ctx: click.Context,
    query: str | None,
    limit: int,
    lang: str | None,
    json_flag: bool,
) -> None:
    """Search DeepWiki for indexed public repositories.

    QUERY is an optional free-text search filter (e.g. repo name fragment).
    Without QUERY, the command lists the most recent indexed repositories.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        with DeepwikiClient() as client:
            indices: list[Index] = client.search(query)
        if lang:
            needle = lang.lower()
            indices = [i for i in indices if (i.language or "").lower() == needle
                       or needle in (i.language or "").lower()]
        if limit and limit > 0:
            indices = indices[:limit]
        emit(indices, json_mode=json_mode, table_renderer=render_index_table)
