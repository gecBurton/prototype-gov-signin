FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Whitenoise's manifest storage 500s if collectstatic has not run, so bake the
# static files into the image. SECRET_KEY and POSTGRES_HOST are only set because
# settings.py refuses to load without them; collectstatic never opens a database
# connection, so the dummy host is fine.
RUN cd iam && SECRET_KEY=build-only POSTGRES_HOST=build-only \
    uv run python manage.py collectstatic --noinput

EXPOSE 8000
CMD cd iam && uv run gunicorn wsgi:application --bind 0.0.0.0:${PORT:-8000}
