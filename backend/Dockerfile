FROM python:3.12-slim AS builder

WORKDIR /srv
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock README.md ./
# Copy all 3 ADK dropdown packages (app, agent_1_without_kc, agent_2_with_kc)
COPY agent/pyproject.toml agent/uv.lock agent/README.md ./agent/
COPY agent/app ./agent/app
COPY agent/agent_1_without_kc ./agent/agent_1_without_kc
COPY agent/agent_2_with_kc ./agent/agent_2_with_kc
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runner

WORKDIR /srv
ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_ENV=production \
    ENABLE_ADK_WEB_UI=true \
    ADK_AGENTS_DIR=/srv/agent \
    GOOGLE_GENAI_USE_VERTEXAI=1 \
    GOOGLE_CLOUD_LOCATION=global \
    GEMINI_MODEL=gemini-4-hydrogen

RUN groupadd --system --gid 1001 appuser && \
    useradd --system --uid 1001 -g appuser -m -d /home/appuser appuser

COPY --from=builder --chown=appuser:appuser /srv /srv

USER 1001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
