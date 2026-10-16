# Hivemind as one self-contained container: FalkorDB (in-memory) + the Hivemind server.
# Runs on any Docker host, including Render free (see render.yaml); listens on $PORT (default 7860), as uid 1000:
#   docker build -f deploy/standalone/Dockerfile -t hivemind-standalone . && docker run -p 7860:7860 hivemind-standalone
# Memory lives only as long as the container; the demo workspace is re-seeded at every start.
# For durable memory, use the main Dockerfile with a persistent FalkorDB (docker-compose.yml or FalkorDB Cloud).
FROM falkordb/falkordb:latest AS falkordb

FROM python:3.11-slim-trixie

# Runtime libraries that redis-server and the FalkorDB module link against.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libstdc++6 libsystemd0 libcap2 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=falkordb /usr/local/bin/redis-server /usr/local/bin/redis-server
COPY --from=falkordb /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so

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

# Bake the embedding model in so the first request isn't a download.
RUN /app/.venv/bin/python -c "from hivemind.embeddings import FastEmbedder; FastEmbedder('/models').embed(['warm up'])"

COPY deploy/standalone/start.sh /app/start.sh
RUN chmod +x /app/start.sh && useradd -m -u 1000 user && chown -R user /app /models
USER user

ENV HIVEMIND_FALKORDB_URL=redis://127.0.0.1:6379 \
    HIVEMIND_PUBLIC=1 \
    PORT=7860 \
    PATH=/app/.venv/bin:$PATH
EXPOSE 7860
CMD ["/app/start.sh"]
