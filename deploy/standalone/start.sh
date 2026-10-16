#!/bin/sh
# Start FalkorDB in the background (memory only, local to the container), seed the demo, serve.
set -e

redis-server --loadmodule /opt/falkordb/falkordb.so \
  --bind 127.0.0.1 --port 6379 --dir /tmp --save "" --appendonly no --daemonize yes

python - <<'EOF'
import time, redis
r = redis.Redis(host="127.0.0.1", port=6379)
for _ in range(100):
    try:
        if r.ping():
            break
    except redis.ConnectionError:
        time.sleep(0.2)
EOF

# A populated dashboard on first visit: replay the scripted multi-agent story quickly.
# Visitors can press "Play the demo" to watch it again in real time.
hivemind demo --workspace demo --speed 40 > /tmp/seed.log 2>&1 || echo "demo seed failed; see /tmp/seed.log"

exec hivemind serve --host 0.0.0.0 --port "${PORT:-7860}"
