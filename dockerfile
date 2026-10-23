FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    build-essential \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libffi-dev \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ARG POETRY_VERSION=1.8.5
RUN pip install --no-cache-dir --upgrade pip setuptools packaging && \
    pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app

COPY pyproject.toml poetry.lock ./
# Poetry installs into the same environment it runs from (no virtualenv) and
# the lock pins older versions of packages already there (e.g. packaging 25.0
# vs the 26.x upgraded above), so it downgrades them mid-install. In parallel
# mode a source build (zope-interface) could read packaging/tags.py while it
# was being replaced: intermittent ChefInstallError / FileNotFoundError in CI
# (2026-10-22, 2026-10-23). Installing serially removes the race.
RUN poetry config virtualenvs.create false \
 && poetry config installer.parallel false \
 && poetry install --only main --no-root

COPY . .

# Run Python by default
ENTRYPOINT ["python3"]