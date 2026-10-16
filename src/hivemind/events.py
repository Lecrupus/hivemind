"""Live events over Redis pub/sub on the same FalkorDB instance.

Every process that writes memory (MCP servers, hook handlers, demo scripts)
publishes here; the dashboard server subscribes and streams to browsers."""

from __future__ import annotations

import json
import logging

from .text import now_ms

CHANNEL = "hivemind:events"
log = logging.getLogger(__name__)


class EventBus:
    def __init__(self, redis_client):
        self.redis = redis_client

    def publish(self, workspace: str, type_: str, **data) -> None:
        payload = {"type": type_, "workspace": workspace, "ts": now_ms(), **data}
        try:
            self.redis.publish(CHANNEL, json.dumps(payload, default=str))
        except Exception as exc:  # events are best-effort; never break a write
            log.debug("event publish failed: %s", exc)

    def subscribe(self):
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(CHANNEL)
        return pubsub
