# Один образ для web / realtime / worker / beat / consumer — различаются командой запуска.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=config.settings

# libldap/libsasl — сборка python-ldap; libgomp1 — рантайм LightGBM; curl — healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libldap2-dev libsasl2-dev libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app

# Зависимости отдельным слоем: пересобираются только при изменении lock-файла
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group ldap --no-install-project

COPY . .
RUN SECRET_KEY=build python manage.py collectstatic --noinput -v0

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /artifacts /tmp/prometheus \
    && chown -R app:app /app/media /artifacts /tmp/prometheus
USER app

EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
