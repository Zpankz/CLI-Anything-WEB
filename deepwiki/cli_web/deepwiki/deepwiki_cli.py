"""cli-web-deepwiki — main CLI entry point.

Registers every command under `commands/` and runs an optional REPL when the
program is invoked with no subcommand.
"""
from __future__ import annotations

import shlex
import sys

# ── UTF-8 stdout/stderr (Windows-safe; idempotent) ────────────────────────────
for _stream in (sys.stdout, sys.stderr):
    _enc = getattr(_stream, "encoding", "") or ""
    if _enc.lower() not in ("utf-8", "utf8"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

from .utils.helpers import ensure_utf8

ensure_utf8()  # idempotent second pass for any wrappers

import click

from .utils.repl_skin import ReplSkin


_skin = ReplSkin(app="deepwiki", version="0.1.0")
_skin.display_name = "DeepWiki"


# ── Main CLI group ────────────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON.")
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output (auto-disabled in --json mode).",
)
@click.version_option("0.1.0", prog_name="dw")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool, no_color: bool):
    """dw — programmatic interface to DeepWiki.

    Run without arguments for interactive REPL mode.

    \b
    Common workflows:
      dw search rust              # find indexed repos
      dw repo owner/repo          # repo overview
      dw wiki owner/repo          # full wiki TOC
      dw page owner/repo/slug -m  # one page as markdown
      dw ask owner/repo "what is X?"
      dw vault owner/repo -o ./vault   # build Obsidian vault

    Pipeline subcommands (work on any HTML/MD, not just DeepWiki):
      parse normalize query convert extract analyze

    Aliases: `cli-web-deepwiki` is also installed for backward compat.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode
    ctx.obj["no_color"] = no_color or json_mode

    if ctx.invoked_subcommand is None:
        _run_repl(ctx)


# ── Register commands (deferred imports so missing optional deps don't break --help)
# Includes the `auth` command group: auth login, auth status, auth reset.
def _register_commands() -> None:
    from .commands import ALL_COMMANDS, auth
    for cmd in ALL_COMMANDS:
        cli.add_command(cmd)
    # `auth` is also a member of ALL_COMMANDS — listed explicitly here for clarity.
    _ = auth


# Eagerly register so `--help` shows all commands
try:
    _register_commands()
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        f"warn: failed to load some commands: {exc}\n"
        f"      Reinstall with `pip install -e .` and ensure deps are present.\n"
    )


# ── REPL ──────────────────────────────────────────────────────────────────────


def _print_repl_help() -> None:
    _skin.info("Available commands:")
    print()
    rows = [
        ("search [query]", "List indexed DeepWiki repos"),
        ("repo <owner/repo>", "Show repo overview + index metadata"),
        ("wiki <owner/repo>", "Show full wiki TOC"),
        ("page <owner/repo/slug> -m", "Fetch one wiki page as markdown"),
        ("ask <owner/repo> <q>", "Ask Devin a question (Q&A)"),
        ("vault <owner/repo> -o DIR", "Generate Obsidian vault"),
        ("graph <owner/repo>", "Wiki graph (mermaid/canvas/json)"),
        ("parse <html-or-url>", "Parse to AST (mdast/hast/nlcst)"),
        ("normalize <md>", "Canonical OFM Markdown"),
        ("query <md> --select X", "AST queries"),
        ("convert --from X --to Y", "Format conversion"),
        ("extract <url>", "Defuddle clean MD extraction"),
        ("analyze <md>", "retext readability/stats/entities"),
        ("lsp", "Start unified-language-server"),
        ("help / exit", "Show this help / quit"),
    ]
    width = max(len(r[0]) for r in rows) + 2
    for cmd, desc in rows:
        print(f"  {cmd:<{width}}{desc}")
    print()


def _run_repl(ctx: click.Context) -> None:
    _skin.print_banner()
    _print_repl_help()
    pt_session = _skin.create_prompt_session()
    while True:
        try:
            line = _skin.get_input(pt_session)
        except (EOFError, KeyboardInterrupt):
            _skin.print_goodbye()
            break
        line = line.strip()
        if not line:
            continue
        if line.lower() in ("exit", "quit", "q", ":q"):
            _skin.print_goodbye()
            break
        if line.lower() in ("help", "?", "h"):
            _print_repl_help()
            continue
        try:
            args = shlex.split(line)
        except ValueError as exc:
            _skin.error(f"Parse error: {exc}")
            continue
        if ctx.obj.get("json"):
            args = ["--json"] + args
        try:
            cli.main(args=args, standalone_mode=False)
        except SystemExit:
            pass
        except click.ClickException as exc:
            _skin.error(exc.format_message())
        except Exception as exc:
            _skin.error(f"{type(exc).__name__}: {exc}")


def main():
    cli()


if __name__ == "__main__":
    main()
