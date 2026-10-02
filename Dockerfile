# API del agente (PA-273): `docker compose --profile full up -d app`.
# Reproducible con el lockfile (`uv sync --frozen`), sin dependencias de desarrollo, con usuario no
# root y sin secretos: el `.env` no se copia (.dockerignore) y llega en tiempo de ejecución con
# `env_file` en docker-compose.yml. Pesa varios GB por torch y docling (ingesta de documentos).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Primero solo las dependencias (capa en caché mientras no cambie el lockfile).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 agente \
    && mkdir -p /app/data/memory \
    && chown -R agente /app/data

USER agente
ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
# Dentro del contenedor escucha en todas sus interfaces; docker-compose.yml solo lo publica en
# 127.0.0.1 de la máquina.
CMD ["python", "-m", "api", "--host", "0.0.0.0", "--port", "8000"]
