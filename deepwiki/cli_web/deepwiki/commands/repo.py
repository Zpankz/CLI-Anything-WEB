"""`cli-web-deepwiki repo` — show full metadata for one DeepWiki-indexed repo."""
from __future__ import annotations

import click

from ..core.client import DeepwikiClient
from ..utils.helpers import emit, handle_errors, parse_repo
from ..utils.output import console, render_repo_card


@click.command("repo")
@click.argument("repo_arg", metavar="OWNER/REPO")
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def repo(ctx: click.Context, repo_arg: str, json_flag: bool) -> None:
    """Show full metadata for a single DeepWiki-indexed repository.

    Combines the Devin Ada index entry (description, stars, language, topics)
    with the DeepWiki SSR overview card (last_indexed timestamp, indexed commit).
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        repo_name = parse_repo(repo_arg)
        with DeepwikiClient() as client:
            index = client.get_index(repo_name)
            overview = client.repo_overview(repo_name)

        combined = {
            "index": index.to_dict() if index is not None else None,
            "overview": overview.to_dict(),
        }

        def _render(_data) -> None:
            render_repo_card(overview)
            if index is None:
                console().print("[yellow]No Ada index entry found for this repo.[/yellow]")
                return
            c = console()
            c.print(
                f"[bold]Description:[/bold] {index.description or '—'}\n"
                f"[bold]Language:[/bold]    {index.language or '—'}\n"
                f"[bold]Stars:[/bold]       {index.stargazers_count:,}\n"
                f"[bold]Topics:[/bold]      {', '.join(index.topics) if index.topics else '—'}\n"
                f"[bold]Index ID:[/bold]    [dim]{index.id}[/dim]\n"
                f"[bold]Modified:[/bold]    {index.last_modified or '—'}"
            )

        emit(combined, json_mode=json_mode, table_renderer=_render)
