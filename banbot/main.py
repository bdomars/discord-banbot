import asyncio
import logging
import ssl

from aiohttp import web
import discord

from banbot.bot import create_client
from banbot.config import Settings
from banbot.web import create_web_app


logger = logging.getLogger("banbot.main")


def create_ssl_context(settings: Settings) -> ssl.SSLContext | None:
    if settings.tls_cert_file is None and settings.tls_key_file is None:
        return None

    if settings.tls_cert_file is None or settings.tls_key_file is None:
        raise ValueError(
            "BANBOT_TLS_CERT_FILE and BANBOT_TLS_KEY_FILE must both be set to enable HTTPS",
        )

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(settings.tls_cert_file, settings.tls_key_file)
    return context


async def run_web(settings: Settings, client: discord.Client) -> None:
    app = create_web_app(settings, client)
    runner = web.AppRunner(app)
    await runner.setup()

    ssl_context = create_ssl_context(settings)
    site = web.TCPSite(
        runner,
        settings.web_host,
        settings.web_port,
        ssl_context=ssl_context,
    )
    await site.start()

    scheme = "https" if ssl_context is not None else "http"
    logger.info("Web UI listening on %s://%s:%s", scheme, settings.web_host, settings.web_port)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def run() -> None:
    settings = Settings.from_env()
    client = create_client(settings)

    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(client.start(settings.discord_token))
        task_group.create_task(run_web(settings, client))


def main() -> None:
    discord.utils.setup_logging(root=True)
    asyncio.run(run())


if __name__ == "__main__":
    main()
