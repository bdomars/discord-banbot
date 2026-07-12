FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim-bookworm

ARG GIT_REV=unknown

LABEL org.opencontainers.image.title="banbot" \
      org.opencontainers.image.description="Discord bot for detecting and banning channel-hopping spam" \
      org.opencontainers.image.revision="${GIT_REV}" \
      org.opencontainers.image.source="https://github.com/bdomars/discord-banbot" \
      org.opencontainers.image.url="https://ghcr.io/bdomars/banbot"

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    BANBOT_GIT_REV="${GIT_REV}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin banbot

COPY --from=builder /app/.venv /app/.venv
COPY banbot.py ./
COPY banbot ./banbot

USER 10001:10001

EXPOSE 8080

ENTRYPOINT ["python", "-m", "banbot.main"]
