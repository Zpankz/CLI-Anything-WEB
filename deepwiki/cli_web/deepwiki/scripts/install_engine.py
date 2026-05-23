"""cli-web-deepwiki-install-engine — bootstrap the Node.js sidecar.

Run after `pip install cli-web-deepwiki` to npm-install the unified_engine
dependencies.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    pkg_root = Path(__file__).resolve().parents[1]
    engine = pkg_root / "unified_engine"
    if not (engine / "package.json").is_file():
        print(
            f"error: unified_engine package.json missing at {engine}",
            file=sys.stderr,
        )
        return 1
    npm = shutil.which("npm")
    if not npm:
        print("error: npm not found on PATH (install Node.js 18+)", file=sys.stderr)
        return 2
    print(f"Installing Node sidecar deps in {engine} ...")
    res = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=str(engine))
    if res.returncode != 0:
        print(f"error: npm install failed (exit {res.returncode})", file=sys.stderr)
        return res.returncode
    print("✓ Sidecar ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
