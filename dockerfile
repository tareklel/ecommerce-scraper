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

ARG POETRY_VERSION=1.7.1
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
 && poetry install --only main --no-root

COPY . .

# Run Python by default
ENTRYPOINT ["python3"]