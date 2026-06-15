FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Whitenoise's manifest storage 500s if collectstatic has not run, so bake the
# static files into the image. SECRET_KEY, POSTGRES_HOST and ALLOWED_HOSTS are
# only set because settings.py refuses to load without them (DEBUG defaults to
# false here, which is when ALLOWED_HOSTS becomes required); collectstatic never
# opens a database connection or serves a request, so the dummy values are fine.
RUN cd iam && SECRET_KEY=build-only POSTGRES_HOST=build-only ALLOWED_HOSTS=build-only \
    uv run python manage.py collectstatic --noinput

EXPOSE 8000
CMD cd iam && uv run gunicorn wsgi:application --bind 0.0.0.0:${PORT:-8000}
