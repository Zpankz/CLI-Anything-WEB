"""Command modules for cli-web-deepwiki.

Each module exposes a single click command (or group) named after the resource.
`ALL_COMMANDS` is the canonical registration list consumed by deepwiki_cli.py.
"""
from __future__ import annotations

from .analyze import analyze
from .ask import ask
from .auth import auth
from .convert import convert
from .extract import extract
from .graph import graph
from .local import local
from .lsp import lsp
from .normalize import normalize
from .page import page
from .parse import parse
from .query import query
from .repo import repo
from .search import search
from .vault import vault
from .wiki import wiki

ALL_COMMANDS = [
    search,
    repo,
    wiki,
    page,
    ask,
    auth,
    parse,
    normalize,
    query,
    convert,
    extract,
    vault,
    graph,
    analyze,
    lsp,
    local,
]

__all__ = [
    "ALL_COMMANDS",
    "analyze",
    "ask",
    "auth",
    "convert",
    "extract",
    "graph",
    "local",
    "lsp",
    "normalize",
    "page",
    "parse",
    "query",
    "repo",
    "search",
    "vault",
    "wiki",
]
