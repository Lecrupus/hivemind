"""The Hivemind server: REST API + live dashboard + hook endpoint + MCP over
streamable HTTP, in one process (`hivemind serve`)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from sse_starlette.sse import EventSourceResponse

from . import hooks
from .config import Settings, slug
from .core import Actor, Hivemind
from .mcp_server import _parse_time, build_server
from .text import now_ms

log = logging.getLogger("hivemind")
WEB = Path(__file__).parent / "web"
FALKORDB_DOWN = (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
CONSOLIDATE_EVERY_S = 300


class EventRelay:
    """Redis pub/sub (shared by every Hivemind process) -> per-browser asyncio queues."""

    def __init__(self, hm: Hivemind):
        self.hm = hm
        self.queues: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        threading.Thread(target=self._run, daemon=True, name="hivemind-events").start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                pubsub = self.hm.events.subscribe()
                while not self._stop.is_set():
                    msg = pubsub.get_message(timeout=1.0)
                    if msg and msg.get("type") == "message":
                        data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                        for q in list(self.queues):
                            self.loop.call_soon_threadsafe(_offer, q, data)
            except Exception as exc:  # reconnect after FalkorDB restarts
                log.warning("event relay reconnecting: %s", exc)
                self._stop.wait(2)


def _offer(q: asyncio.Queue, item: str) -> None:
    if q.qsize() < 500:
        q.put_nowait(item)


def create_app(settings: Settings | None = None, hm: Hivemind | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    hm = hm or Hivemind(settings)
    mcp = build_server(hm, settings)
    public = os.environ.get("HIVEMIND_PUBLIC") == "1"
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=not public,
                                                     allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                                                     allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]),
    )
    relay = EventRelay(hm)
    demo_lock = threading.Lock()

    async def consolidate_loop():
        while True:
            await asyncio.sleep(CONSOLIDATE_EVERY_S)
            try:
                workspaces = await anyio.to_thread.run_sync(hm.list_workspaces)
            except Exception as exc:  # FalkorDB down: try again next round
                log.warning("consolidation skipped: %s", exc)
                continue
            for ws in workspaces:
                try:
                    a = Actor(workspace=ws["workspace"], user="system", agent_id="hivemind@system", client="system")
                    await anyio.to_thread.run_sync(lambda: hm.consolidate(a))
                except Exception as exc:
                    log.warning("consolidate %s failed: %s", ws["workspace"], exc)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        relay.start(asyncio.get_running_loop())
        task = asyncio.create_task(consolidate_loop())
        await anyio.to_thread.run_sync(lambda: hm.embed("warm up"))  # load the model before the first hook
        async with mcp.session_manager.run():
            yield
        task.cancel()
        relay.stop()

    app = FastAPI(title="Hivemind", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(redis.exceptions.ConnectionError)
    @app.exception_handler(redis.exceptions.TimeoutError)
    async def falkordb_down(request: Request, exc: Exception):
        return JSONResponse({"error": "FalkorDB is unreachable", "detail": str(exc)}, status_code=503)

    def check_key(request: Request) -> None:
        if settings.api_key and request.headers.get("authorization") != f"Bearer {settings.api_key}":
            raise HTTPException(401, "missing or wrong API key")

    @app.middleware("http")
    async def protect_mcp(request: Request, call_next):
        if request.url.path.startswith("/mcp") and settings.api_key:
            if request.headers.get("authorization") != f"Bearer {settings.api_key}":
                return JSONResponse({"error": "missing or wrong API key"}, status_code=401)
        return await call_next(request)

    def viewer(workspace: str) -> Actor:
        return Actor(workspace=slug(workspace), user="viewer", agent_id="dashboard@viewer", client="dashboard")

    def from_headers(request: Request) -> Actor:
        h = request.headers
        user = slug(h["x-hivemind-user"]) if h.get("x-hivemind-user") else settings.user
        client = slug(h["x-hivemind-client"]) if h.get("x-hivemind-client") else "claude-code"
        return Actor(workspace=slug(h.get("x-hivemind-workspace") or settings.workspace), user=user,
                     agent_id=h.get("x-hivemind-agent") or f"{client}@{user}", client=client,
                     role=h.get("x-hivemind-role") or None)

    async def run(fn, *args, **kwargs):
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------ hooks

    @app.post("/api/hook/{event}")
    async def hook(event: str, request: Request):
        check_key(request)
        payload = await request.json()
        actor = from_headers(request)
        try:
            return JSONResponse(await run(hooks.handle, hm, event, payload, actor))
        except Exception as exc:  # a hook must never break the agent
            log.exception("hook %s failed", event)
            if event != "session-start":
                return JSONResponse({})
            msg = ("Hivemind can't reach FalkorDB; team memory is off until it's back."
                   if isinstance(exc, FALKORDB_DOWN) else f"Hivemind hook error: {exc}")
            return JSONResponse({"systemMessage": msg})

    # ------------------------------------------------------------ dashboard API

    @app.get("/api/health")
    async def health():
        # The server is up whenever this answers; `falkordb` says whether memory is reachable.
        return {"ok": True, "falkordb": await run(hm.db.ping), "embedder": hm.embedder.name}

    @app.get("/api/workspaces")
    async def workspaces():
        return await run(hm.list_workspaces)

    @app.get("/api/graph")
    async def graph(workspace: str = "demo", as_of: str | None = None, user: str | None = None, limit: int = 400):
        return await run(hm.graph_view, slug(workspace), as_of=_parse_time(as_of), limit=min(limit, 1500),
                         user=slug(user) if user else None)

    @app.get("/api/stats")
    async def stats(workspace: str = "demo"):
        a = viewer(workspace)
        s = await run(hm.stats, a)
        assists = await run(hm.db.ro_query, hm.shared(a),
                            "MATCH (e:Episode {kind: 'assist'}) RETURN count(e) AS n")
        s["assists"] = assists[0]["n"] if assists else 0
        since = {"since": now_ms() - 3_600_000}
        recent = await run(hm.db.ro_query, hm.shared(a), _RECENT, since)
        s["recent"] = {r["label"]: r["n"] for r in recent}
        ra = await run(hm.db.ro_query, hm.shared(a),
                       "MATCH (e:Episode {kind: 'assist'}) WHERE e.ts >= $since RETURN count(e) AS n", since)
        s["recent_assists"] = ra[0]["n"] if ra else 0
        return s

    @app.get("/api/node")
    async def node(workspace: str, id: str, user: str | None = None):
        return await run(hm.node_detail, slug(workspace), id, user=slug(user) if user else None)

    @app.get("/api/why")
    async def why(workspace: str, id: str):
        return await run(hm.why, viewer(workspace), id)

    @app.get("/api/recall")
    async def recall(workspace: str, q: str, as_of: str | None = None, k: int = 8):
        return await run(hm.recall, viewer(workspace), q, k=k, as_of=_parse_time(as_of), include_private=False,
                         bump=False)

    @app.get("/api/team")
    async def team(workspace: str = "demo"):
        a = viewer(workspace)
        return {"agents": await run(hm.team_status, a, 120), "tasks": await run(hm.list_tasks, a),
                "handoffs": await run(hm.db.ro_query, hm.shared(a), _HANDOFFS, {})}

    @app.get("/api/timeline")
    async def timeline(workspace: str, entity: str):
        return await run(hm.timeline, viewer(workspace), entity)

    @app.get("/api/feed")
    async def feed(workspace: str = "demo", limit: int = 60):
        return await run(hm.db.ro_query, hm.shared(viewer(workspace)), _FEED, {"limit": min(limit, 300)})

    @app.get("/api/time-range")
    async def time_range(workspace: str = "demo"):
        rows = await run(hm.db.ro_query, hm.shared(viewer(workspace)), _RANGE, {})
        return rows[0] if rows else {"min": None, "max": None}

    @app.post("/api/consolidate")
    async def consolidate(workspace: str = "demo"):
        return await run(hm.consolidate, viewer(workspace))

    @app.get("/api/bench")
    async def bench():
        out = {}
        for f in sorted((WEB / "bench").glob("*.json")):
            out[f.stem] = json.loads(f.read_text())
        return out

    # ------------------------------------------------------------ live demo

    @app.post("/api/demo/play")
    async def demo_play(workspace: str = "demo", speed: float = 1.0, reset: bool = True):
        from . import demo

        # The demo resets its workspace, so the button may only ever touch the demo one.
        if slug(workspace) != "demo":
            raise HTTPException(400, "the scripted demo only runs in the 'demo' workspace")
        if not demo_lock.acquire(blocking=False):
            return JSONResponse({"status": "already playing"}, status_code=409)

        def go():
            try:
                demo.play(hm, slug(workspace), speed=max(0.2, min(speed, 5.0)), reset=reset)
            finally:
                demo_lock.release()

        threading.Thread(target=go, daemon=True, name="hivemind-demo").start()
        return {"status": "playing", "workspace": slug(workspace)}

    @app.get("/api/demo/status")
    async def demo_status():
        return {"playing": demo_lock.locked()}

    @app.get("/api/events")
    async def events(request: Request, workspace: str | None = None):
        q: asyncio.Queue = asyncio.Queue()
        relay.queues.add(q)

        async def stream():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield {"event": "ping", "data": "{}"}
                        continue
                    if workspace and json.loads(item).get("workspace") != slug(workspace):
                        continue
                    yield {"event": "memory", "data": item}
            finally:
                relay.queues.discard(q)

        return EventSourceResponse(stream())

    # ------------------------------------------------------------ static dashboard + MCP

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    app.mount("/", mcp_app)  # serves POST /mcp
    return app


_HANDOFFS = """
MATCH (h:Handoff)-[:OF]->(t:Task)
RETURN h.id AS id, h.ts AS ts, h.summary AS summary, h.status AS status, h.from_agent AS from_agent,
       coalesce(h.to_agent, h.to_role, 'anyone') AS to, t.title AS task, t.id AS task_id, h.accepted_by AS accepted_by
ORDER BY h.ts DESC LIMIT 20
"""

_FEED = """
MATCH (n)
WHERE (n:Episode AND NOT n.kind IN ['learning', 'edit', 'assist', 'handoff']) OR n:Fact OR n:Procedure OR n:Handoff OR n:Task
WITH n, coalesce(n.recorded_at, n.ts, n.created_at) AS t
RETURN labels(n)[0] AS label, n.id AS id, t AS ts, n.kind AS kind, n.status AS status,
       coalesce(n.statement, n.goal, n.text, n.summary, n.title) AS text,
       coalesce(n.agent_id, n.source_agent, n.created_by, n.from_agent) AS agent
ORDER BY t DESC LIMIT $limit
"""

_RECENT = """
MATCH (n)
WITH labels(n)[0] AS label, coalesce(n.recorded_at, n.ts, n.created_at, n.started_at, 0) AS t
WHERE t >= $since
RETURN label, count(*) AS n
"""

_RANGE = """
MATCH (n) WHERE n:Episode OR n:Fact OR n:Procedure OR n:Task OR n:Handoff
WITH coalesce(n.recorded_at, n.ts, n.created_at) AS t
RETURN min(t) AS min, max(t) AS max
"""
