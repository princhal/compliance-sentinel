# Playwright's image ships Chromium and its system dependencies. Its tag must match the
# playwright version in uv.lock.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"

# WeasyPrint needs Pango; git is used to check out audited repositories.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY sentinel ./sentinel
COPY migrations ./migrations
COPY alembic.ini ./
COPY demo-target-repo ./demo-target-repo
COPY evals ./evals
RUN uv sync --frozen --no-dev && useradd --create-home sentinel && mkdir -p /data \
    && chown -R sentinel /data /app
USER sentinel
ENV DATA_DIR=/data
EXPOSE 8080
CMD ["sentinel", "api", "--port", "8080"]
