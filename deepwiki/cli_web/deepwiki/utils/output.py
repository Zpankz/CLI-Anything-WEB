"""Rich-powered tables and panels for human-readable output."""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from ..core.models import CodemapResult


_console = Console()


def console() -> Console:
    return _console


# ── tables ────────────────────────────────────────────────────────────────────


def render_index_table(indices: Iterable) -> None:
    """Render Index list as a table."""
    t = Table(title="DeepWiki indexed repositories", show_lines=False)
    t.add_column("Repo", style="cyan", no_wrap=True)
    t.add_column("Lang", style="magenta")
    t.add_column("Stars", justify="right", style="yellow")
    t.add_column("Last indexed", style="dim")
    t.add_column("Description")
    for idx in indices:
        commit = (idx.commit_sha or "")[:8]
        t.add_row(
            idx.repo_name,
            idx.language or "—",
            f"{idx.stargazers_count:,}",
            f"{(idx.last_modified or '')[:10]} {commit}",
            (idx.description or "")[:80],
        )
    _console.print(t)


def render_repo_card(card) -> None:
    panel = Panel(
        f"[cyan bold]{card.repo}[/cyan bold]\n"
        f"Last indexed: [yellow]{card.last_indexed or '—'}[/yellow]  "
        f"commit: [green]{(card.indexed_commit or '')[:8]}[/green]",
        title=card.title,
        border_style="cyan",
    )
    _console.print(panel)


def render_wiki_tree(tree) -> None:
    t = Table(title=f"{tree.repo} — wiki TOC ({len(tree.pages)} pages)")
    t.add_column("#", style="dim", no_wrap=True)
    t.add_column("Slug", style="cyan", no_wrap=True)
    t.add_column("Title")
    for i, p in enumerate(tree.pages, 1):
        t.add_row(str(i), p.slug, p.title)
    _console.print(t)


def render_page(page, *, render_md: bool = True) -> None:
    head = (
        f"[cyan bold]{page.title}[/cyan bold]\n"
        f"slug: [yellow]{page.slug}[/yellow]\n"
        f"url:  [dim]{page.url}[/dim]"
    )
    _console.print(Panel(head, border_style="cyan"))
    if render_md and page.markdown:
        _console.print(Markdown(page.markdown))


def render_answer(query, *, show_thoughts: bool = False, show_tool_calls: bool = False) -> None:
    """Render a Devin Q&A answer as a panel + markdown body.

    show_thoughts: also render any agentic reasoning trace (omni/agent/planning).
    show_tool_calls: also render tool invocations the agent made.
    """
    head = (
        f"[bold cyan]Q:[/bold cyan] {query.title.split('</relevant_context>',1)[-1]}\n"
        f"[dim]engine: {(query.latest.engine_id if query.latest else '?')} | "
        f"turns: {query.turn_count} | state: {query.state}[/dim]"
    )
    _console.print(Panel(head, border_style="cyan"))

    if show_thoughts:
        for i, t in enumerate(query.thoughts, 1):
            _console.print(Panel(
                Markdown(t),
                title=f"[dim]thought {i}[/dim]",
                border_style="dim magenta",
            ))

    if show_tool_calls and query.tool_calls:
        tcs = Table(title=f"Tool calls ({len(query.tool_calls)})", show_lines=False)
        tcs.add_column("Phase", style="yellow")
        tcs.add_column("Tool", style="cyan")
        for tc in query.tool_calls:
            data = tc.get("data") or {}
            name = data.get("name") or data.get("tool") or data.get("type") or "—"
            tcs.add_row(tc.get("phase", "?"), str(name))
        _console.print(tcs)

    md = query.answer_markdown
    if md.strip():
        _console.print(Markdown(md))
    refs = query.references
    if refs:
        _console.print()
        t = Table(title=f"References ({len(refs)})", show_lines=False)
        t.add_column("File", style="cyan")
        t.add_column("Lines", style="yellow")
        for r in refs:
            t.add_row(r.file_path, f"L{r.range_start}-L{r.range_end}")
        _console.print(t)


def render_codemap(result: "CodemapResult", query) -> None:
    """Render a codemap result with traces, diagrams, and locations."""
    head = (
        f"[bold cyan]{result.title}[/bold cyan]\n"
        f"[dim]engine: codemap | traces: {len(result.traces)} | "
        f"playground links: {len(result.playground_links)}[/dim]"
    )
    _console.print(Panel(head, border_style="cyan"))

    for trace in result.traces:
        _console.print(f"\n[bold yellow]━━━ Trace {trace.id}: {trace.title}[/bold yellow]")
        _console.print(f"[dim]{trace.description}[/dim]\n")

        if trace.text_diagram:
            _console.print(Panel(
                trace.text_diagram,
                title=f"[dim]Architecture Diagram[/dim]",
                border_style="dim green",
            ))

        if trace.locations:
            t = Table(show_lines=False, box=None)
            t.add_column("ID", style="yellow", no_wrap=True)
            t.add_column("Location", style="cyan")
            t.add_column("Description")
            for loc in trace.locations:
                t.add_row(
                    loc.id,
                    f"{loc.path}:{loc.line_number}",
                    loc.title,
                )
            _console.print(t)

    if result.playground_links:
        _console.print(f"\n[bold]Playground Links[/bold] ({len(result.playground_links)})")
        for i, link in enumerate(result.playground_links, 1):
            _console.print(f"  [dim]{i}.[/dim] [blue underline]{link}[/blue underline]")


def render_progress(query) -> None:
    """One-line progress callback for ask command."""
    state = query.state
    n = len(query.primary.response) if query.primary else 0
    _console.print(f"[dim]ask • state={state} • blocks={n}[/dim]")


def info(msg: str) -> None:
    _console.print(f"[dim cyan]i[/dim cyan] {msg}")


def success(msg: str) -> None:
    _console.print(f"[bold green]✓[/bold green] {msg}")


def warn(msg: str) -> None:
    _console.print(f"[yellow]⚠[/yellow]  {msg}")


def error(msg: str) -> None:
    _console.print(f"[bold red]✗[/bold red] {msg}", style="red")
