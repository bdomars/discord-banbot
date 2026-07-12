from banbot.bot import create_client
from banbot.config import Settings


def main() -> None:
    settings = Settings.from_env()
    client = create_client(settings)
    client.run(settings.discord_token, root_logger=True)


if __name__ == "__main__":
    main()
