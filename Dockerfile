# syntax=docker/dockerfile:1
# Production image for tuck-it on Cloud Run.
FROM python:3.13-slim

# uv binary (pin the tag to match local uv major/minor).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install deps first so this layer caches across code changes. --no-install-project
# skips building tuck-it itself here (no source yet); --no-dev omits test tooling.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App code, then finalize the environment (installs tuck-it into .venv).
COPY . .
RUN uv sync --frozen --no-dev

# Bake static assets into the image. WhiteNoise's manifest storage (used when
# DEBUG=0) requires a collectstatic manifest to exist. collectstatic loads
# settings — which hard-require DATABASE_URL / SECRET_KEY / ALLOWED_HOSTS — but
# never touches the database, so throwaway build-time values are safe and are
# NOT used at runtime (Cloud Run injects the real env).
RUN DJANGO_DEBUG=0 \
    DJANGO_SECRET_KEY=build-time-placeholder-not-used-at-runtime \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:///build-noop.sqlite3 \
    /app/.venv/bin/python manage.py collectstatic --noinput

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

# Cloud Run routes traffic to $PORT (8080 by default) and sends SIGTERM on
# shutdown. Call the venv's gunicorn directly (not `uv run`) so the inner `exec`
# makes gunicorn PID 1 — it receives SIGTERM and drains in-flight requests
# gracefully (zero-downtime rollouts).
#
# NOTE: database migrations are NOT run here — they run as a separate deploy
# step (a Cloud Run Job / CI step) so scaled instances don't race, per the
# expand/contract migration discipline in docs/cloud-deployment-spec.md §5.
ENV PORT=8080
CMD ["sh", "-c", "exec /app/.venv/bin/gunicorn tuckit.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 --graceful-timeout 30 --access-logfile - --error-logfile -"]
