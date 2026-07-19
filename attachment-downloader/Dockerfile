FROM ghcr.io/astral-sh/uv:python3.9-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra gmail

COPY . .
RUN uv sync --frozen --no-dev --extra gmail

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "attachment_downloader.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
