import html
import logging
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web

from banbot.config import Settings


logger = logging.getLogger("banbot.web")

DISCORD_API_BASE = "https://discord.com/api/v10"
SESSION_COOKIE = "banbot_session"
ADMINISTRATOR_PERMISSION = 0x8


@dataclass
class WebSession:
    access_token: str
    user: Mapping[str, object]
    created_at: float


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, WebSession] = {}
        self.pending_states: dict[str, float] = {}

    def create_pending_state(self) -> str:
        state = secrets.token_urlsafe(32)
        self.pending_states[state] = time.monotonic()
        return state

    def consume_pending_state(self, state: str) -> bool:
        created_at = self.pending_states.pop(state, None)
        if created_at is None:
            return False

        return time.monotonic() - created_at <= 10 * 60

    def create_session(
        self,
        access_token: str,
        user: Mapping[str, object],
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        self.sessions[session_id] = WebSession(
            access_token=access_token,
            user=user,
            created_at=time.monotonic(),
        )
        return session_id

    def get(self, request: web.Request) -> WebSession | None:
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id is None:
            return None

        return self.sessions.get(session_id)

    def delete(self, session_id: str | None) -> None:
        if session_id is not None:
            self.sessions.pop(session_id, None)


def html_page(title: str, body: str) -> web.Response:
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f7fb;
      color: #18202f;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }}
    main {{
      width: min(100% - 32px, 720px);
    }}
    h1 {{
      margin: 0 0 20px;
      font-size: 28px;
      line-height: 1.15;
      font-weight: 700;
    }}
    label {{
      display: block;
      margin-bottom: 8px;
      font-weight: 650;
    }}
    select, button, .button {{
      min-height: 44px;
      border: 1px solid #c8d0df;
      border-radius: 8px;
      font: inherit;
    }}
    select {{
      width: 100%;
      padding: 0 12px;
      background: #ffffff;
      color: #18202f;
    }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      padding: 0 16px;
      background: #5865f2;
      color: #ffffff;
      text-decoration: none;
      font-weight: 700;
      cursor: pointer;
    }}
    .panel {{
      margin-top: 20px;
      border: 1px solid #dce2ee;
      border-radius: 8px;
      background: #ffffff;
      overflow: hidden;
    }}
    .row {{
      display: grid;
      grid-template-columns: minmax(140px, 220px) 1fr;
      gap: 16px;
      padding: 14px 16px;
      border-top: 1px solid #edf0f6;
    }}
    .row:first-child {{
      border-top: 0;
    }}
    .key {{
      color: #526071;
      font-weight: 650;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 20px;
    }}
    .logout {{
      color: #526071;
      font-size: 14px;
    }}
    .empty {{
      margin-top: 16px;
      color: #526071;
    }}
    @media (max-width: 560px) {{
      .row {{
        grid-template-columns: 1fr;
        gap: 4px;
      }}
      .topbar {{
        align-items: flex-start;
        flex-direction: column;
      }}
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        background: #10141d;
        color: #eef3fb;
      }}
      select, .panel {{
        background: #171d29;
        border-color: #303849;
        color: #eef3fb;
      }}
      .row {{
        border-top-color: #283142;
      }}
      .key, .empty, .logout {{
        color: #aab5c5;
      }}
    }}
  </style>
</head>
<body>
  <main>{body}</main>
</body>
</html>"""
    return web.Response(text=document, content_type="text/html")


def login_page(settings: Settings) -> web.Response:
    disabled = not settings.discord_client_id or not settings.discord_client_secret
    if disabled:
        body = """
<h1>Banbot</h1>
<p class="empty">Discord OAuth is not configured yet.</p>
"""
    else:
        body = """
<h1>Banbot</h1>
<a class="button" href="/login">Log in with Discord</a>
"""

    return html_page("Banbot", body)


async def exchange_code(settings: Settings, code: str) -> dict[str, object]:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_oauth_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            if response.status != 200:
                body = await response.text()
                logger.warning("Discord token exchange failed: %s %s", response.status, body)
                raise web.HTTPBadGateway(text="Discord token exchange failed")

            return await response.json()


async def fetch_discord_json(access_token: str, path: str) -> object:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            if response.status != 200:
                body = await response.text()
                logger.warning("Discord API request failed: %s %s", response.status, body)
                raise web.HTTPBadGateway(text="Discord API request failed")

            return await response.json()


def is_admin_guild(guild: Mapping[str, object]) -> bool:
    if guild.get("owner") is True:
        return True

    permissions = guild.get("permissions")
    if permissions is None:
        return False

    return int(str(permissions)) & ADMINISTRATOR_PERMISSION == ADMINISTRATOR_PERMISSION


def bot_guilds_by_id(client: discord.Client) -> dict[int, discord.Guild]:
    return {guild.id: guild for guild in client.guilds}


def available_guilds(
    user_guilds: object,
    client: discord.Client,
) -> list[tuple[int, str]]:
    if not isinstance(user_guilds, list):
        return []

    bot_guilds = bot_guilds_by_id(client)
    guilds: list[tuple[int, str]] = []

    for guild in user_guilds:
        if not isinstance(guild, Mapping) or not is_admin_guild(guild):
            continue

        guild_id = int(str(guild["id"]))
        bot_guild = bot_guilds.get(guild_id)
        if bot_guild is None:
            continue

        guilds.append((guild_id, bot_guild.name))

    return sorted(guilds, key=lambda item: item[1].casefold())


def settings_panel(settings: Settings, guild: discord.Guild | None) -> str:
    if guild is None:
        return ""

    rows = [
        ("Log channel", f"#{settings.log_channel_name}"),
        ("Dry run", str(settings.dry_run)),
        ("Detection window", f"{settings.window_seconds} seconds"),
        ("Channel threshold", str(settings.max_channels)),
        ("Retention", f"{settings.retention_seconds} seconds"),
    ]
    row_html = "\n".join(
        f"""<div class="row"><div class="key">{html.escape(key)}</div><div>{html.escape(value)}</div></div>"""
        for key, value in rows
    )
    return f"""<section class="panel" aria-label="Settings for {html.escape(guild.name)}">{row_html}</section>"""


async def dashboard(
    request: web.Request,
    settings: Settings,
    client: discord.Client,
    sessions: SessionStore,
) -> web.Response:
    web_session = sessions.get(request)
    if web_session is None:
        return login_page(settings)

    user_guilds = await fetch_discord_json(web_session.access_token, "/users/@me/guilds")
    guilds = available_guilds(user_guilds, client)
    allowed_guild_ids = {guild_id for guild_id, _name in guilds}
    selected_id = None
    selected_guild_id = request.query.get("guild_id")

    if selected_guild_id is not None:
        try:
            requested_id = int(selected_guild_id)
        except ValueError:
            requested_id = None

        if requested_id in allowed_guild_ids:
            selected_id = requested_id

    if selected_id is None and guilds:
        selected_id = guilds[0][0]

    selected_guild = bot_guilds_by_id(client).get(selected_id) if selected_id is not None else None

    options = "\n".join(
        f"""<option value="{guild_id}"{" selected" if guild_id == selected_id else ""}>{html.escape(name)}</option>"""
        for guild_id, name in guilds
    )
    user_name = html.escape(str(web_session.user.get("username", "Discord user")))

    if guilds:
        selector = f"""
<form method="get">
  <label for="guild_id">Guild</label>
  <select id="guild_id" name="guild_id" onchange="this.form.submit()">
    {options}
  </select>
</form>
{settings_panel(settings, selected_guild)}
"""
    else:
        selector = """<p class="empty">No shared guilds found where you are an administrator and Banbot is installed.</p>"""

    body = f"""
<div class="topbar">
  <h1>Banbot</h1>
  <a class="logout" href="/logout">Logged in as {user_name}. Log out</a>
</div>
{selector}
"""
    return html_page("Banbot settings", body)


def create_web_app(settings: Settings, client: discord.Client) -> web.Application:
    sessions = SessionStore()
    app = web.Application()

    async def index(request: web.Request) -> web.Response:
        return await dashboard(request, settings, client, sessions)

    async def login(request: web.Request) -> web.Response:
        if not settings.discord_client_id or not settings.discord_client_secret:
            raise web.HTTPServiceUnavailable(text="Discord OAuth is not configured")

        state = sessions.create_pending_state()
        params = urlencode({
            "client_id": settings.discord_client_id,
            "redirect_uri": settings.discord_oauth_redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        })
        return web.HTTPFound(location=f"{DISCORD_API_BASE}/oauth2/authorize?{params}")

    async def oauth_callback(request: web.Request) -> web.Response:
        state = request.query.get("state")
        code = request.query.get("code")
        if not state or not code or not sessions.consume_pending_state(state):
            raise web.HTTPBadRequest(text="Invalid OAuth state")

        token_response = await exchange_code(settings, code)
        access_token = token_response.get("access_token")
        if not isinstance(access_token, str):
            raise web.HTTPBadGateway(text="Discord token response did not include an access token")

        user = await fetch_discord_json(access_token, "/users/@me")
        if not isinstance(user, Mapping):
            raise web.HTTPBadGateway(text="Discord user response was invalid")

        session_id = sessions.create_session(access_token, user)
        response = web.HTTPFound(location="/")
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            httponly=True,
            samesite="Lax",
            max_age=60 * 60 * 8,
        )
        return response

    async def logout(request: web.Request) -> web.Response:
        sessions.delete(request.cookies.get(SESSION_COOKIE))
        response = web.HTTPFound(location="/")
        response.del_cookie(SESSION_COOKIE)
        return response

    app.router.add_get("/", index)
    app.router.add_get("/login", login)
    app.router.add_get("/oauth/callback", oauth_callback)
    app.router.add_get("/logout", logout)

    return app
