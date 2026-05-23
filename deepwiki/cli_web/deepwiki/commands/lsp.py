"""`cli-web-deepwiki lsp` — start the unified-language-server bridge."""
from __future__ import annotations

import os
import shutil

import click

from ..utils.helpers import handle_errors
from ..utils.output import info
from ..utils.unified_bridge import UnifiedBridge, UnifiedBridgeError


@click.command("lsp")
@click.option(
    "--stdio/--tcp",
    default=True,
    show_default=True,
    help="Use stdio transport (default) or TCP. Combine with --port for TCP.",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="TCP port for the LSP server (only with --tcp).",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON status before exec (no-op for stdio).",
)
@click.pass_context
def lsp(
    ctx: click.Context,
    stdio: bool,
    port: int | None,
    json_flag: bool,
) -> None:
    """Start the unified-language-server LSP bridge.

    In --stdio mode (default) this process is replaced (execvp) by the Node LSP,
    so it can be wired straight into editor LSP clients. In --tcp mode the LSP
    is launched in TCP listen mode on --port.
    """
    json_mode = json_flag or bool((ctx.obj or {}).get("json"))
    with handle_errors(json_mode=json_mode):
        if not stdio and port is None:
            raise click.BadParameter("--tcp requires --port")

        # Resolve sidecar dir without spawning the server.js bridge.
        bridge = UnifiedBridge()
        sidecar_dir = bridge._dir
        lsp_js = sidecar_dir / "lsp.js"
        if not lsp_js.is_file():
            raise UnifiedBridgeError(
                f"LSP entry point missing: {lsp_js}. Ensure the unified_engine "
                f"sidecar is installed (`npm install --prefix {sidecar_dir}`)."
            )

        node = shutil.which("node")
        if not node:
            raise UnifiedBridgeError(
                "Node.js not found on PATH. Install Node 18+ from https://nodejs.org/"
            )

        argv = [node, str(lsp_js)]
        if stdio:
            argv.append("--stdio")
        else:
            argv += ["--tcp", "--port", str(port)]
            if not json_mode:
                info(f"Starting unified-language-server on TCP :{port}")

        # Replace the Python process so editor LSP clients talk directly to Node.
        os.execvp(argv[0], argv)
