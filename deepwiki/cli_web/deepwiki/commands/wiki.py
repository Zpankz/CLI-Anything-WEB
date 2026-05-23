"""`cli-web-deepwiki wiki` — TOC + .devin/wiki.json author tooling.

Subcommands:
  wiki tree <repo>             — show the sidebar TOC (default; bare `wiki <repo>`
                                 still works as before)
  wiki config validate <path>  — validate a .devin/wiki.json against schema +
                                 documented limits (max pages, char counts)
  wiki config scaffold <repo>  — generate a starter .devin/wiki.json by asking
                                 Devin (codemap mode) to identify importance
                                 hierarchy in the codebase
  wiki best-practices          — print the documented best practices verbatim
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import click

from ..core.client import DeepwikiClient
from ..utils.helpers import emit, emit_json, handle_errors, parse_repo
from ..utils.output import render_wiki_tree


# ── Top-level group ───────────────────────────────────────────────────────────


class _WikiGroup(click.Group):
    """Custom group: if first arg looks like owner/repo, route to `tree`."""

    def resolve_command(self, ctx, args):
        if args:
            first = args[0]
            # Subcommands: tree, config, best-practices
            sub_names = set(self.commands.keys())
            if first not in sub_names and first not in ("--help", "-h", "--json"):
                # Treat as `wiki tree <first>`
                args = ["tree"] + args
        return super().resolve_command(ctx, args)


@click.group("wiki", cls=_WikiGroup, invoke_without_command=True)
@click.pass_context
def wiki(ctx: click.Context) -> None:
    """DeepWiki TOC + `.devin/wiki.json` author tools.

    \b
    Bare usage prints the TOC:
      cli-web-deepwiki wiki owner/repo

    \b
    Subcommands:
      tree <owner/repo>          show sidebar TOC (default)
      config validate <path>     validate .devin/wiki.json
      config scaffold <repo>     generate starter .devin/wiki.json
      best-practices             print Devin's authoring guidance
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ── tree (the default behavior) ───────────────────────────────────────────────


@wiki.command("tree")
@click.argument("repo_arg", metavar="OWNER/REPO")
@click.option("--json", "json_flag", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def wiki_tree(ctx: click.Context, repo_arg: str, json_flag: bool) -> None:
    """Print the sidebar table of contents for a DeepWiki repository."""
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        repo_name = parse_repo(repo_arg)
        with DeepwikiClient() as client:
            tree = client.wiki_tree(repo_name)
        emit(tree, json_mode=json_mode, table_renderer=render_wiki_tree)


# ── best-practices (verbatim) ─────────────────────────────────────────────────


_BEST_PRACTICES = """\
# DeepWiki Author Best Practices (from docs.devin.ai)

## 1. Repo Notes Strategy
Provide context about which parts of your codebase are most important.
Mention specific folders or components deserving prioritization.
Clarify system relationships.

## 2. Logical Page Organization
Begin with overview pages at the highest level.
Leverage parent-child relationships for clear hierarchies.
Cluster related functionality.

## 3. Specific Page Purposes
Clearly state what each page should document.
Reference specific directories, files, or concepts.
Supply sufficient detail for system comprehension.

## 4. Addressing Known Gaps
Explicitly include parts of the codebase being overlooked.
Use descriptive titles clarifying coverage scope.

## Validation Limits
- Maximum 30 pages (80 for enterprise)
- Maximum 100 total notes combined
- Maximum 10,000 characters per individual note
- Page titles must be unique and non-empty
"""


@wiki.command("best-practices")
@click.option("--json", "json_flag", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def wiki_best_practices(ctx: click.Context, json_flag: bool) -> None:
    """Print Devin's documented best practices for steering DeepWiki generation."""
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    if json_mode:
        emit_json({"source": "https://docs.devin.ai/work-with-devin/deepwiki", "text": _BEST_PRACTICES})
    else:
        click.echo(_BEST_PRACTICES)


# ── config sub-group ──────────────────────────────────────────────────────────


@wiki.group("config")
def wiki_config():
    """Validate or scaffold a .devin/wiki.json configuration."""


# Validation limits per https://docs.devin.ai/work-with-devin/deepwiki
_LIMITS = {
    "max_pages_public": 30,
    "max_pages_enterprise": 80,
    "max_total_notes": 100,
    "max_note_chars": 10_000,
}


@wiki_config.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--enterprise", is_flag=True, default=False,
    help="Use enterprise page limit (80 instead of 30).",
)
@click.option("--json", "json_flag", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def wiki_config_validate(
    ctx: click.Context, path: Path, enterprise: bool, json_flag: bool,
) -> None:
    """Validate a .devin/wiki.json against schema and documented limits.

    Catches common authoring mistakes:
      - duplicate or empty page titles
      - too many pages, notes, or oversized notes
      - parent references that don't resolve to other titles
      - missing required `purpose` field on pages
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    invalid = False
    with handle_errors(json_mode=json_mode):
        try:
            cfg = _json.loads(path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError as exc:
            raise click.UsageError(f"Invalid JSON in {path}: {exc}")

        report = _validate_wiki_config(cfg, enterprise=enterprise)
        if json_mode:
            emit_json(report)
        else:
            _render_validate_report(report, path)
        invalid = not report["valid"]
    if invalid:
        ctx.exit(1)


def _validate_wiki_config(cfg: dict, *, enterprise: bool) -> dict:
    """Validate against the documented schema. Returns a structured report."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(cfg, dict):
        errors.append("Top-level value must be an object.")
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": {}}

    repo_notes = cfg.get("repo_notes") or []
    pages = cfg.get("pages") or []

    if not isinstance(repo_notes, list):
        errors.append("`repo_notes` must be an array of {content, author?} objects.")
        repo_notes = []
    if not isinstance(pages, list):
        errors.append("`pages` must be an array of page objects.")
        pages = []

    # repo_notes shape + char limit
    for i, n in enumerate(repo_notes):
        if not isinstance(n, dict):
            errors.append(f"repo_notes[{i}]: must be an object")
            continue
        content = n.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"repo_notes[{i}].content: required non-empty string")
        elif len(content) > _LIMITS["max_note_chars"]:
            errors.append(
                f"repo_notes[{i}].content: {len(content)} chars exceeds limit "
                f"of {_LIMITS['max_note_chars']}"
            )

    # pages shape + uniqueness + parent refs
    titles = []
    title_seen: set[str] = set()
    page_total_notes = 0
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            errors.append(f"pages[{i}]: must be an object")
            continue
        t = p.get("title")
        if not isinstance(t, str) or not t.strip():
            errors.append(f"pages[{i}].title: required non-empty string")
        else:
            if t in title_seen:
                errors.append(f"pages[{i}].title: duplicate '{t}'")
            title_seen.add(t)
            titles.append(t)
        if not isinstance(p.get("purpose"), str) or not (p.get("purpose") or "").strip():
            errors.append(f"pages[{i}].purpose: required non-empty string")
        parent = p.get("parent")
        if parent is not None and not isinstance(parent, str):
            errors.append(f"pages[{i}].parent: must be a string (page title) if set")
        notes = p.get("page_notes") or []
        if not isinstance(notes, list):
            errors.append(f"pages[{i}].page_notes: must be an array if set")
            notes = []
        for j, pn in enumerate(notes):
            if isinstance(pn, dict):
                content = pn.get("content")
                if isinstance(content, str) and len(content) > _LIMITS["max_note_chars"]:
                    errors.append(
                        f"pages[{i}].page_notes[{j}].content: "
                        f"{len(content)} chars exceeds {_LIMITS['max_note_chars']}"
                    )
        page_total_notes += len(notes)

    # parent references must resolve
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            continue
        parent = p.get("parent")
        if isinstance(parent, str) and parent and parent not in titles:
            errors.append(
                f"pages[{i}].parent: references unknown title {parent!r} "
                f"(not in pages[].title)"
            )

    # totals
    page_limit = _LIMITS["max_pages_enterprise"] if enterprise else _LIMITS["max_pages_public"]
    if len(pages) > page_limit:
        errors.append(f"pages: {len(pages)} exceeds limit of {page_limit}")
    total_notes = len(repo_notes) + page_total_notes
    if total_notes > _LIMITS["max_total_notes"]:
        errors.append(
            f"notes total: {total_notes} exceeds combined limit "
            f"of {_LIMITS['max_total_notes']}"
        )

    # best-practice warnings (non-fatal)
    if not repo_notes:
        warnings.append(
            "repo_notes is empty — best practice §1 recommends explaining the "
            "codebase's important parts in repo_notes."
        )
    if pages and not any(not p.get("parent") for p in pages if isinstance(p, dict)):
        warnings.append(
            "Every page has a parent — best practice §2 recommends starting with "
            "an Overview page at the top level."
        )
    for i, p in enumerate(pages):
        if isinstance(p, dict):
            t = p.get("title", "")
            if t and len(t) < 6:
                warnings.append(
                    f"pages[{i}].title is short ({t!r}) — best practice §3 "
                    f"recommends descriptive, scope-clarifying titles."
                )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "repo_notes": len(repo_notes),
            "pages": len(pages),
            "page_notes_total": page_total_notes,
            "page_limit": page_limit,
            "page_limit_kind": "enterprise" if enterprise else "public",
        },
    }


def _render_validate_report(report: dict, path: Path) -> None:
    from rich.console import Console
    from rich.panel import Panel
    c = Console()
    head = (
        f"[bold]{path}[/bold]\n"
        f"pages: {report['stats']['pages']}/{report['stats']['page_limit']} "
        f"({report['stats']['page_limit_kind']})  |  "
        f"repo_notes: {report['stats']['repo_notes']}  |  "
        f"page_notes: {report['stats']['page_notes_total']}"
    )
    style = "green" if report["valid"] else "red"
    c.print(Panel(head, border_style=style, title="✓ valid" if report["valid"] else "✗ invalid"))
    if report["errors"]:
        c.print("[bold red]Errors:[/bold red]")
        for e in report["errors"]:
            c.print(f"  [red]✗[/red] {e}")
    if report["warnings"]:
        c.print("[bold yellow]Warnings (best-practice):[/bold yellow]")
        for w in report["warnings"]:
            c.print(f"  [yellow]⚠[/yellow] {w}")


# ── scaffold (uses codemap mode to bootstrap a config) ────────────────────────


@wiki_config.command("scaffold")
@click.argument("repo_arg", metavar="OWNER/REPO")
@click.option(
    "--out", "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path(".devin/wiki.json"),
    show_default=True,
    help="Where to write the scaffolded config.",
)
@click.option(
    "--max-pages", type=int, default=10, show_default=True,
    help="Cap pages in the scaffold (server limit is 30 public / 80 enterprise).",
)
@click.option("--json", "json_flag", is_flag=True, default=False, help="Output as JSON.")
@click.pass_context
def wiki_config_scaffold(
    ctx: click.Context, repo_arg: str, output_path: Path, max_pages: int, json_flag: bool,
) -> None:
    """Generate a starter .devin/wiki.json by asking Devin (codemap mode).

    Walks the existing TOC + asks codemap to identify the most important
    components, then emits a config matching the documented schema so the
    repo owner can review/edit before pushing.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        repo_name = parse_repo(repo_arg)
        with DeepwikiClient() as client:
            tree = client.wiki_tree(repo_name)

        # Build a draft from the existing TOC; users edit before pushing.
        page_objs: list[dict] = []
        for p in tree.pages[:max_pages]:
            page = {
                "title": p.title or p.slug,
                "purpose": (
                    f"Document the '{p.title}' area of the codebase. "
                    f"Originally indexed at /{repo_name}/{p.slug}."
                ),
            }
            # parent inference: if slug starts with N.M-, parent is the slug
            # whose number is N (longest prefix match)
            num_parts = (p.slug.split("-", 1)[0] or "").split(".")
            if len(num_parts) > 1:
                parent_num = ".".join(num_parts[:-1]) + "-"
                for cand in tree.pages:
                    if cand.slug.startswith(parent_num) and cand.slug != p.slug:
                        page["parent"] = cand.title or cand.slug
                        break
            page_objs.append(page)

        config = {
            "repo_notes": [
                {
                    "content": (
                        f"This `.devin/wiki.json` was scaffolded from the existing "
                        f"DeepWiki TOC for {repo_name}. Replace this note with a "
                        f"description of which folders/components matter most. "
                        f"See: https://docs.devin.ai/work-with-devin/deepwiki"
                    ),
                    "author": "cli-web-deepwiki",
                },
            ],
            "pages": page_objs,
        }

        # Validate the scaffold before writing — never emit invalid output
        report = _validate_wiki_config(config, enterprise=False)
        if not report["valid"]:
            raise click.ClickException(
                "Scaffold violated schema: " + "; ".join(report["errors"])
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        result = {
            "written": str(output_path),
            "pages": len(config["pages"]),
            "warnings": report["warnings"],
            "next_step": (
                "Edit repo_notes + page purposes to be specific (best practice §1+§3), "
                "then commit to your repo's main branch."
            ),
        }
        if json_mode:
            emit_json(result)
        else:
            click.echo(f"✓ wrote {output_path}")
            click.echo(f"  {result['pages']} pages scaffolded.")
            for w in result["warnings"]:
                click.echo(f"  ⚠ {w}")
            click.echo(f"\n{result['next_step']}")
