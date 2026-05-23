"""Python ↔ Node.js bridge to the unified ecosystem.

The Node sidecar lives at `cli_web/deepwiki/unified_engine/` and is invoked as a
long-lived child process. We send line-delimited JSON-RPC requests on stdin and
read JSON responses on stdout. One request per line; one response per line.

This is the only place in the Python tree that imports `subprocess`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from importlib import resources
from pathlib import Path
from queue import Queue, Empty
from typing import Any

from ..core.exceptions import DeepwikiError


class UnifiedBridgeError(DeepwikiError):
    """Sidecar misbehaved (bad json, non-zero exit, missing dependency)."""


class UnifiedBridge:
    """Long-lived JSON-RPC client to the Node `unified_engine` sidecar.

    Usage:
        with UnifiedBridge() as ub:
            res = ub.call("htmlToMd", {"html": html, "options": {...}})
            print(res["markdown"])
    """

    def __init__(self, sidecar_dir: Path | None = None, env: dict | None = None):
        self._dir = sidecar_dir or _default_sidecar_dir()
        self._proc: subprocess.Popen | None = None
        self._stderr_q: Queue[str] = Queue()
        self._env = env

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._proc is not None:
            return
        node = _resolve_node()
        server_js = self._dir / "server.js"
        if not server_js.is_file():
            raise UnifiedBridgeError(
                f"Sidecar entry point missing: {server_js}. "
                f"Run `npm install --prefix {self._dir}` after installing cli-web-deepwiki."
            )
        node_modules = self._dir / "node_modules"
        if not node_modules.is_dir():
            raise UnifiedBridgeError(
                f"Sidecar deps not installed. Run: "
                f"npm install --prefix {self._dir}"
            )
        env = {**os.environ, **(self._env or {})}
        self._proc = subprocess.Popen(
            [node, str(server_js)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._dir),
            env=env,
            bufsize=1,
            text=True,
            encoding="utf-8",
        )
        # Drain stderr asynchronously so it doesn't block
        t = threading.Thread(target=self._drain_stderr, daemon=True)
        t.start()

    def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        for line in self._proc.stderr:
            self._stderr_q.put(line.rstrip())

    def stop(self) -> None:
        if not self._proc:
            return
        try:
            self._proc.stdin and self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            self._proc.kill()
        self._proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    # ── JSON-RPC ──────────────────────────────────────────────────────────────

    def call(self, method: str, params: dict | None = None) -> Any:
        """Invoke a sidecar method. Blocks until response received."""
        if self._proc is None:
            self.start()
        assert self._proc and self._proc.stdin and self._proc.stdout

        req_id = str(uuid.uuid4())
        line = json.dumps({"id": req_id, "method": method, "params": params or {}})
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError:
            err_lines = self._collect_stderr()
            raise UnifiedBridgeError(
                f"Sidecar pipe closed unexpectedly. Stderr tail:\n{err_lines}"
            )

        # Read response line(s); skip non-JSON noise
        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                err_lines = self._collect_stderr()
                raise UnifiedBridgeError(
                    f"Sidecar terminated without responding to {method}. "
                    f"Stderr tail:\n{err_lines}"
                )
            raw = raw.strip()
            if not raw:
                continue
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue  # ignore stray output
            if resp.get("id") != req_id:
                continue  # response to an earlier abandoned call
            if not resp.get("ok"):
                raise UnifiedBridgeError(
                    f"{method} failed: {resp.get('error') or resp}"
                )
            return resp.get("data")

    def _collect_stderr(self, max_lines: int = 25) -> str:
        out: list[str] = []
        try:
            while len(out) < max_lines:
                out.append(self._stderr_q.get_nowait())
        except Empty:
            pass
        return "\n".join(out)

    # ── high-level conveniences ───────────────────────────────────────────────

    def html_to_md(self, html: str, *, base_url: str | None = None) -> dict:
        return self.call("htmlToMd", {"html": html, "baseUrl": base_url})

    def html_to_mdast(self, html: str) -> dict:
        return self.call("htmlToMdast", {"html": html})

    def md_to_ofm(self, markdown: str, *, options: dict | None = None) -> dict:
        return self.call("mdToOfm", {"markdown": markdown, "options": options or {}})

    def md_to_nlcst(self, markdown: str) -> dict:
        return self.call("mdToNlcst", {"markdown": markdown})

    def ast_query(self, tree: dict, *, type: str = "mdast", selector: str = "") -> dict:
        return self.call("astQuery", {"tree": tree, "type": type, "selector": selector})

    def ast_convert(self, *, input: str, frm: str, to: str) -> dict:
        return self.call("astConvert", {"input": input, "from": frm, "to": to})

    def vault_page(self, html: str, *, ctx: dict) -> dict:
        return self.call("vaultPage", {"html": html, "ctx": ctx})

    def vault_moc(self, *, repo: str, pages: list[dict], structure: list[dict]) -> dict:
        return self.call("vaultMoc", {"repo": repo, "pages": pages, "structure": structure})

    def vault_canvas(self, *, repo: str, pages: list[dict], links: list[dict]) -> dict:
        return self.call("vaultCanvas", {"repo": repo, "pages": pages, "links": links})

    def lsp(self, *, action: str = "start", port: int | None = None, stdio: bool = True) -> dict:
        return self.call("lsp", {"action": action, "port": port, "stdio": stdio})

    def analyze(self, markdown: str) -> dict:
        return self.call("analyze", {"markdown": markdown})


# ── helpers ────────────────────────────────────────────────────────────────────


def _default_sidecar_dir() -> Path:
    """Locate unified_engine/ inside the installed package or development tree."""
    # 1. Bundled inside the package (production install)
    try:
        with resources.as_file(
            resources.files("cli_web.deepwiki").joinpath("unified_engine")
        ) as p:
            if p.is_dir():
                return Path(p)
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    # 2. Sibling to the package (development checkout)
    here = Path(__file__).resolve()
    cand = here.parents[1] / "unified_engine"
    if cand.is_dir():
        return cand
    cand = here.parents[3] / "unified_engine"  # agent-harness/unified_engine
    if cand.is_dir():
        return cand
    raise UnifiedBridgeError("Cannot locate unified_engine sidecar directory.")


def _resolve_node() -> str:
    node = shutil.which("node")
    if not node:
        raise UnifiedBridgeError(
            "Node.js not found on PATH. Install Node 18+ from https://nodejs.org/"
        )
    return node
