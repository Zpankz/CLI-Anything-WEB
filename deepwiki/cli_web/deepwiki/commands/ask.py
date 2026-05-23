"""`cli-web-deepwiki ask` — submit a Q&A query and stream the answer.

Supports three execution modes (fast / research / codemap) and follow-up
questions on existing threads. Modes map to Devin Ada `engine_id` values.
"""
from __future__ import annotations

import click

from ..core.client import DeepwikiClient, resolve_engine, MODE_ALIASES, ENGINE_IDS
from ..core.models import Query, CodemapResult
from ..core.session import Session
from ..utils.helpers import emit, handle_errors, parse_repo
from ..utils.output import render_answer, render_codemap, render_progress


# ── friendly mode set surfaced in --help (a curated subset of MODE_ALIASES) ──
_VISIBLE_MODES = ["fast", "research", "codemap", "agent", "omni", "planning"]


@click.command("ask")
@click.argument("repo_arg", metavar="OWNER/REPO", required=False)
@click.argument("question", required=False)
@click.option(
    "--mode",
    type=str,
    default="fast",
    show_default=True,
    metavar="MODE",
    help=(
        "Engine: fast (multihop_faster) | research (multihop) | codemap | "
        "agent | omni | planning. Or any raw engine_id."
    ),
)
@click.option(
    "--context",
    "wiki_page",
    type=str,
    default=None,
    metavar="SLUG",
    help="Wiki page slug to attach as relevant_context to the prompt.",
)
@click.option(
    "--follow-up", "-f",
    "follow_up_id",
    type=str,
    default=None,
    metavar="QUERY_ID",
    help="Append this question as a follow-up to an existing thread.",
)
@click.option(
    "--continue",
    "continue_last",
    is_flag=True,
    default=False,
    help="Continue the most recent query thread (uses session's last_query_id).",
)
@click.option(
    "--thread",
    "show_thread",
    is_flag=True,
    default=False,
    help="Print the entire thread transcript (all turns), not just the latest answer.",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    show_default=True,
    help="Block until the query reaches a terminal state. With --no-wait, returns the query_id.",
)
@click.option(
    "--list-modes",
    is_flag=True,
    default=False,
    help="Print all valid engine_ids and aliases, then exit.",
)
@click.option(
    "--show-thoughts",
    is_flag=True,
    default=False,
    help="Render the agent's reasoning trace (omni/agent/planning engines emit these).",
)
@click.option(
    "--show-tool-calls",
    is_flag=True,
    default=False,
    help="Render tool invocations made by the agent during the query.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Output as JSON.",
)
@click.pass_context
def ask(
    ctx: click.Context,
    repo_arg: str | None,
    question: str | None,
    mode: str,
    wiki_page: str | None,
    follow_up_id: str | None,
    continue_last: bool,
    show_thread: bool,
    wait: bool,
    list_modes: bool,
    show_thoughts: bool,
    show_tool_calls: bool,
    json_flag: bool,
) -> None:
    """Ask Devin a question about an indexed repository.

    \b
    Examples:
      ask owner/repo "What does this project do?"             # fast (default)
      ask owner/repo "Explain the architecture" --mode research
      ask owner/repo "Map the public API surface" --mode codemap
      ask owner/repo "More detail on point 3" --continue      # follow-up
      ask owner/repo "Specifically about X" -f QUERY_ID       # explicit follow-up
      ask --no-wait owner/repo "..." --json                   # async submit
      ask --list-modes                                         # show all engines
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))

    if list_modes:
        modes_data = {
            "engine_ids": list(ENGINE_IDS),
            "aliases": MODE_ALIASES,
            "default": "multihop_faster (alias: fast)",
            "common": {
                "fast": "multihop_faster — Quick answer, ~3-8s",
                "research": "multihop — Deeper multi-hop reasoning, ~15-30s",
                "codemap": "codemap — Structural/symbol map of the codebase",
            },
        }
        emit(modes_data, json_mode=json_mode)
        return

    with handle_errors(json_mode=json_mode):
        if not repo_arg or not question:
            raise click.UsageError("Both OWNER/REPO and QUESTION are required (unless --list-modes).")

        repo = parse_repo(repo_arg)
        engine_id = resolve_engine(mode)

        # Resolve follow-up target
        session = Session.load()
        if continue_last:
            if follow_up_id:
                raise click.UsageError("Use either --continue or --follow-up, not both.")
            follow_up_id = session.last_query_id
            if not follow_up_id:
                raise click.UsageError(
                    "No prior query in session. Run an `ask` first, then use --continue."
                )

        with DeepwikiClient() as client:
            if not wait:
                qid = client.ada.submit_query(
                    question,
                    repo,
                    engine_id=engine_id,
                    wiki_page=wiki_page,
                    query_id=follow_up_id,
                )
                # persist for --continue
                session.last_query_id = qid
                session.save()
                payload = {
                    "submitted": True,
                    "query_id": qid,
                    "repo": repo,
                    "engine_id": engine_id,
                    "is_follow_up": follow_up_id is not None,
                }
                emit(payload, json_mode=json_mode)
                return

            on_progress = None if json_mode else render_progress
            final: Query = client.ask(
                question,
                repo,
                engine_id=engine_id,
                wiki_page=wiki_page,
                query_id=follow_up_id,
                on_progress=on_progress,
            )
            # Persist this thread's id for --continue next time
            actual_qid = getattr(final, "_query_id", None) or follow_up_id
            if actual_qid:
                session.last_query_id = actual_qid
                session.save()

        if show_thread:
            emit(
                {
                    "title": final.title,
                    "turn_count": final.turn_count,
                    "transcript": final.transcript,
                },
                json_mode=json_mode,
            )
        elif engine_id == "codemap":
            codemap_result = CodemapResult.from_query(final)
            if json_mode:
                emit(codemap_result.to_dict(), json_mode=True)
            else:
                render_codemap(codemap_result, final)
        else:
            def _render(q):
                render_answer(q, show_thoughts=show_thoughts, show_tool_calls=show_tool_calls)
            emit(final, json_mode=json_mode, table_renderer=_render)


