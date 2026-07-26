FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 reviewforge \
    && mkdir -p /data \
    && chown -R reviewforge:reviewforge /app /data
USER reviewforge

ENV CHECKPOINT_DB=/data/reviewforge-checkpoints.sqlite
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["reviewforge-server"]

