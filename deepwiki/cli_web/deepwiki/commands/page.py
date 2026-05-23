"""`cli-web-deepwiki page` — fetch a single wiki page (HTML or Markdown)."""
from __future__ import annotations

import click

from ..core.client import DeepwikiClient
from ..utils.helpers import emit, handle_errors, parse_repo_and_slug
from ..utils.output import render_page
from ..utils.unified_bridge import UnifiedBridge


@click.command("page")
@click.argument("page_arg", metavar="OWNER/REPO/SLUG")
@click.option(
    "--markdown",
    "-m",
    "as_markdown",
    is_flag=True,
    default=False,
    help="Pipe HTML through unified to produce clean Markdown.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def page(
    ctx: click.Context,
    page_arg: str,
    as_markdown: bool,
    json_flag: bool,
) -> None:
    """Fetch a single DeepWiki page.

    Argument may be `owner/repo/slug` or a full DeepWiki URL.

    Without --markdown, outputs the page metadata only. With --markdown, the page
    HTML is piped through the unified pipeline (defuddle + rehype + remark) to
    produce canonical Markdown.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        repo, slug = parse_repo_and_slug(page_arg)
        if not slug:
            raise click.BadParameter(
                "page command requires owner/repo/slug — got owner/repo only.",
            )

        with DeepwikiClient() as client:
            pg = client.fetch_page(repo, slug)

        if as_markdown:
            with UnifiedBridge() as bridge:
                result = bridge.html_to_md(pg.html or "", base_url=pg.url)
            pg.markdown = result.get("markdown")
            meta = result.get("metadata") or {}
            if meta:
                pg.metadata = {**(pg.metadata or {}), **meta}

        def _render(_data) -> None:
            render_page(pg, render_md=as_markdown)

        emit(pg, json_mode=json_mode, table_renderer=_render)
