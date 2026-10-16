"""FalkorDB access: one graph per workspace (shared team memory) plus one
graph per user inside a workspace (private memory). A single FalkorDB
instance holds all of them, which is how tenants stay isolated."""

from __future__ import annotations

import threading
from typing import Any

import redis
from falkordb import FalkorDB
from falkordb.edge import Edge
from falkordb.node import Node
from falkordb.path import Path

from . import queries as Q

GRAPH_PREFIX = "hivemind_"
PRIVATE_SEP = "__"


def shared_graph_name(workspace: str) -> str:
    return f"{GRAPH_PREFIX}{workspace}"


def private_graph_name(workspace: str, user: str) -> str:
    return f"{GRAPH_PREFIX}{workspace}{PRIVATE_SEP}{user}"


def parse_graph_name(name: str) -> tuple[str, str | None] | None:
    """'hivemind_acme' -> ('acme', None); 'hivemind_acme__bob' -> ('acme', 'bob')."""
    if not name.startswith(GRAPH_PREFIX):
        return None
    rest = name[len(GRAPH_PREFIX):]
    if PRIVATE_SEP in rest:
        ws, user = rest.split(PRIVATE_SEP, 1)
        return ws, user
    return rest, None


def _plain(value: Any) -> Any:
    """Convert FalkorDB result values into JSON-friendly Python values."""
    if isinstance(value, Node):
        props = {k: v for k, v in value.properties.items() if k != "embedding"}
        return {"_kind": "node", "_id": value.id, "labels": list(value.labels or []), **props}
    if isinstance(value, Edge):
        props = {k: v for k, v in value.properties.items()}
        return {"_kind": "edge", "_id": value.id, "type": value.relation,
                "src": value.src_node, "dst": value.dest_node, **props}
    if isinstance(value, Path):
        return {"_kind": "path", "nodes": [_plain(n) for n in value.nodes()],
                "edges": [_plain(e) for e in value.edges()]}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class GraphDB:
    """Thin wrapper around the FalkorDB client with schema bootstrapping."""

    def __init__(self, url: str, embedding_dim: int):
        self.url = url
        self.dim = embedding_dim
        self._lock = threading.Lock()
        self._client = None
        # Fail fast when FalkorDB is unreachable (one quick retry, short connect timeout)
        # instead of redis-py's multi-second backoff, so callers can report the outage.
        self._conn_opts = {"socket_connect_timeout": 1.5,
                           "retry": redis.retry.Retry(redis.backoff.NoBackoff(), 1)}
        # Plain Redis client for pub/sub and pings. It connects lazily, so the server
        # can start (and keep serving) while FalkorDB is down, and recovers when it returns.
        self.redis = redis.Redis.from_url(url, **self._conn_opts)
        self._graphs: dict[str, Any] = {}
        self._ready: set[str] = set()

    @property
    def client(self) -> FalkorDB:
        # FalkorDB.from_url talks to the server immediately, so create it on first use.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = FalkorDB.from_url(self.url, **self._conn_opts)
        return self._client

    def graph(self, name: str):
        g = self._graphs.get(name)
        if g is None:
            g = self.client.select_graph(name)
            self._graphs[name] = g
        if name not in self._ready:
            self._ensure_schema(name, g)
        return g

    def _ensure_schema(self, name: str, g) -> None:
        with self._lock:
            if name in self._ready:
                return
            for stmt in Q.schema_statements(self.dim):
                try:
                    g.query(stmt)
                except Exception as exc:  # index already exists
                    msg = str(exc).lower()
                    if "already" not in msg and "exists" not in msg:
                        raise
            self._ready.add(name)

    def query(self, graph: str, cypher: str, params: dict | None = None) -> list[dict]:
        res = self.graph(graph).query(cypher, params or {})
        return _rows(res)

    def ro_query(self, graph: str, cypher: str, params: dict | None = None) -> list[dict]:
        res = self.graph(graph).ro_query(cypher, params or {})
        return _rows(res)

    def list_graphs(self) -> list[str]:
        return list(self.client.list_graphs())

    def graph_exists(self, name: str) -> bool:
        return name in self.list_graphs()

    def delete_graph(self, name: str) -> None:
        if self.graph_exists(name):
            self.client.select_graph(name).delete()
        self._graphs.pop(name, None)
        self._ready.discard(name)

    def ping(self) -> bool:
        try:
            return bool(self.redis.ping())
        except Exception:
            return False


def _rows(res) -> list[dict]:
    if not res.header:
        return []
    names = [h[1] for h in res.header]
    return [{n: _plain(v) for n, v in zip(names, row)} for row in res.result_set]
