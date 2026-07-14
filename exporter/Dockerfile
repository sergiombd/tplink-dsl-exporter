FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
RUN uv sync --no-dev

COPY exporter.py ./

EXPOSE 9908

# exporter.py carries PEP 723 inline deps; `uv sync` above pre-warms the cache
# so this start-up resolve is instant.
CMD ["uv", "run", "exporter.py"]
