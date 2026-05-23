"""auth — manage the optional devin_client_uuid cookie + session state."""
from __future__ import annotations

import json

import click

from ..core import auth as auth_mod
from ..core.session import Session
from ..utils.helpers import handle_errors, emit_json


@click.group("auth")
def auth():
    """Manage cookies and session.

    DeepWiki + Devin Ada API don't require login. The CLI persists the
    `devin_client_uuid` cookie that Devin issues on first POST so calls
    are attributed consistently across invocations. Use `auth login`
    to mint a fresh cookie, `auth status` to inspect, `auth reset` to
    clear all session state.
    """


@auth.command("status")
@click.pass_context
def auth_status(ctx):
    """Show whether session cookies are persisted."""
    json_mode = bool(ctx.obj and ctx.obj.get("json"))
    with handle_errors(json_mode=json_mode):
        s = auth_mod.status()
        sess = Session.load().to_dict()
        data = {**s, "session": sess}
        if json_mode:
            emit_json(data)
        else:
            click.echo(f"authenticated: {data['authenticated']}")
            click.echo(f"cookies:       {data['cookie_count']}")
            click.echo(f"current_repo:  {sess.get('current_repo') or '—'}")
            click.echo(f"config_dir:    {data['config_dir']}")
            if data['env_override']:
                click.echo("note:          using CLI_WEB_DEEPWIKI_AUTH_JSON env override")


@auth.command("login")
@click.pass_context
def auth_login(ctx):
    """Mint a fresh devin_client_uuid by issuing a probe POST.

    Optional — calls work anonymously. Run this only if you want a stable
    client UUID for usage attribution.
    """
    json_mode = bool(ctx.obj and ctx.obj.get("json"))
    with handle_errors(json_mode=json_mode):
        from ..core.client import DevinAdaClient
        with DevinAdaClient() as c:
            # Issue a no-op-ish call that triggers the cookie set
            _ = c.list_public_indexes(search_repo="deepwiki")
            cookies = c.cookies
        if cookies:
            auth_mod.save_cookies(cookies)
        if json_mode:
            emit_json({"ok": True, "cookies_saved": len(cookies)})
        else:
            click.echo(f"✓ cookies persisted ({len(cookies)})")


@auth.command("reset")
@click.pass_context
@click.confirmation_option(prompt="Clear all session cookies?")
def auth_reset(ctx):
    """Wipe all persisted cookies and session state."""
    json_mode = bool(ctx.obj and ctx.obj.get("json"))
    with handle_errors(json_mode=json_mode):
        auth_mod.clear()
        if json_mode:
            emit_json({"ok": True})
        else:
            click.echo("✓ session cleared")
