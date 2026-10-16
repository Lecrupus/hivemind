FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HIVEMIND_MODEL_CACHE=/models

RUN pip install --no-cache-dir uv==0.11.2
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY README.md ./
RUN uv sync --frozen --no-dev

# Bake the embedding model into the image so the first request isn't a download.
RUN uv run --no-sync python -c "from hivemind.embeddings import FastEmbedder; FastEmbedder('/models').embed(['warm up'])"

ENV HIVEMIND_PUBLIC=1 PORT=8765
EXPOSE 8765
CMD ["sh", "-c", "uv run --no-sync hivemind serve --host 0.0.0.0 --port ${PORT}"]
