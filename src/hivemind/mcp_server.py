"""MCP server: Hivemind's memory and coordination tools for any MCP client
(Claude Code, Cursor, Codex, Windsurf, custom agents).

Identity comes from HTTP headers (X-Hivemind-Workspace / -User / -Agent /
-Client / -Role) when served over HTTP, or from HIVEMIND_* env vars on stdio."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from .config import Settings, slug
from .core import Actor, Hivemind

INSTRUCTIONS = """\
Hivemind is shared, persistent memory for a team of AI agents, stored as a graph in FalkorDB.
Other agents (and your own past sessions) write here; what you learn helps them.

- Before non-trivial work, `recall` what the team knows about it. If recall says nothing matches, don't assume.
- When you discover something durable (a convention, a gotcha, a config detail, a decision and why),
  `learn` it. Use `key` for facts that have one current value (e.g. "db.engine") so updates supersede.
- When something you knew turns out wrong or changed, `supersede` it instead of adding a contradiction.
- When you work out how to do something (build, test, deploy, fix a recurring error), `record_procedure`
  with the exact steps; when you follow a known procedure, `report_outcome`.
- Coordinate: `claim_task` before starting shared work, `handoff` with a summary and next steps when you
  stop, check `inbox` and `team_status` to avoid duplicating or colliding with teammates.
- `why` explains where any memory came from. Facts marked private stay in your user's private memory.
"""


def _parse_time(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int) or str(value).isdigit():
        return int(value)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def build_server(hm: Hivemind, settings: Settings | None = None) -> MCPServer:
    settings = settings or hm.settings
    mcp = MCPServer("hivemind", instructions=INSTRUCTIONS, version="0.1.0")

    def actor(ctx: Context | None) -> Actor:
        h: dict[str, str] = {}
        try:
            raw = ctx.headers if ctx is not None else None
            h = {k.lower(): v for k, v in (raw or {}).items()}
        except Exception:
            pass
        user = slug(h["x-hivemind-user"]) if h.get("x-hivemind-user") else None
        client = slug(h["x-hivemind-client"]) if h.get("x-hivemind-client") else None
        a = Actor.from_settings(
            settings,
            workspace=slug(h["x-hivemind-workspace"]) if h.get("x-hivemind-workspace") else None,
            user=user,
            client=client,
            role=h.get("x-hivemind-role") or None,
        )
        a.agent_id = h.get("x-hivemind-agent") or (f"{a.client}@{a.user}" if (user or client) else a.agent_id)
        return a

    async def run(fn, *args, **kwargs) -> Any:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------ recall & facts

    @mcp.tool()
    async def recall(query: str, k: int = 8, as_of: str | None = None, ctx: Context = None) -> dict:
        """Search team memory (facts, procedures, past episodes) with hybrid vector + keyword + graph
        retrieval. Each result says why it ranked and where it came from. `as_of` (ISO date) answers
        "what did we believe then?"."""
        return await run(hm.recall, actor(ctx), query, k=k, as_of=_parse_time(as_of))

    @mcp.tool()
    async def learn(statement: str, kind: str = "fact", key: str | None = None, about: list[str] | None = None,
                    confidence: float = 0.8, private: bool = False, ctx: Context = None) -> dict:
        """Store a durable fact for the team. kind: fact | convention | gotcha | config | decision |
        preference. `key` names a single-valued fact (e.g. "frontend.package_manager"): a new value
        supersedes the old one. `about` lists files/modules/commands it concerns. private=True keeps it
        in your user's private memory. Near-duplicates are reinforced, likely contradictions are returned."""
        return await run(hm.learn, actor(ctx), statement, kind=kind, key=key, about=about,
                         confidence=confidence, private=private)

    @mcp.tool()
    async def supersede(old_id: str, new_statement: str, reason: str = "", ctx: Context = None) -> dict:
        """Replace a fact that is no longer true. The old fact is kept as history (valid_to is set) and
        linked to its replacement."""
        return await run(hm.supersede, actor(ctx), old_id, new_statement=new_statement, reason=reason)

    @mcp.tool()
    async def forget(id: str, reason: str = "", hard: bool = False, ctx: Context = None) -> dict:
        """Retract a fact, procedure or episode (kept for audit, never recalled). hard=True deletes it and
        anything derived only from it."""
        return await run(hm.forget, actor(ctx), id, reason=reason, hard=hard)

    @mcp.tool()
    async def promote(fact_id: str, ctx: Context = None) -> dict:
        """Share one of your private facts with the whole team."""
        return await run(hm.promote, actor(ctx), fact_id)

    @mcp.tool()
    async def why(id: str, ctx: Context = None) -> dict:
        """Explain a memory: which agent learned it, in which session, from what episode, what it replaced
        or was replaced by, and which handoffs carried it."""
        return await run(hm.why, actor(ctx), id)

    @mcp.tool()
    async def timeline(entity: str, ctx: Context = None) -> list[dict]:
        """How the team's knowledge about a file, module or tool changed over time (including superseded facts)."""
        return await run(hm.timeline, actor(ctx), entity)

    @mcp.tool()
    async def connect(a: str, b: str, ctx: Context = None) -> dict:
        """Shortest path between two entities or memories in the graph, to explain how they relate."""
        return await run(hm.connect, actor(ctx), a, b)

    # ------------------------------------------------------------ episodes

    @mcp.tool()
    async def remember(text: str, kind: str = "note", about: list[str] | None = None, private: bool = False,
                       ctx: Context = None) -> dict:
        """Record something that happened in this session (a decision, an observation, an outcome)."""
        return await run(hm.remember, actor(ctx), text, kind=kind, about=about, private=private)

    @mcp.tool()
    async def history(query: str | None = None, limit: int = 20, ctx: Context = None) -> list[dict]:
        """Conversation and work history across all sessions and agents: most recent first, or the most
        relevant to `query`."""
        return await run(hm.history, actor(ctx), query=query, limit=limit)

    # ------------------------------------------------------------ procedures

    @mcp.tool()
    async def record_procedure(goal: str, steps: list[str], outcome: str = "success",
                               about: list[str] | None = None, ctx: Context = None) -> dict:
        """Save how to accomplish something as exact steps (commands or actions). outcome: success | failure.
        Recording the same steps again reinforces them; different steps become a new revision."""
        return await run(hm.record_procedure, actor(ctx), goal, steps, outcome=outcome, about=about)

    @mcp.tool()
    async def find_procedure(goal: str, k: int = 3, ctx: Context = None) -> list[dict]:
        """Find how the team does something, ranked by relevance and success rate."""
        return await run(hm.find_procedure, actor(ctx), goal, k=k)

    @mcp.tool()
    async def report_outcome(procedure_id: str, success: bool, notes: str = "", ctx: Context = None) -> dict:
        """Report whether following a procedure worked, so the team's ranking of how-tos stays honest."""
        return await run(hm.report_outcome, actor(ctx), procedure_id, success, notes)

    # ------------------------------------------------------------ coordination

    @mcp.tool()
    async def create_task(title: str, description: str = "", about: list[str] | None = None, claim: bool = True,
                          ctx: Context = None) -> dict:
        """Create a shared task (and claim it by default)."""
        return await run(hm.create_task, actor(ctx), title, description, about=about, claim=claim)

    @mcp.tool()
    async def claim_task(task_id: str, ctx: Context = None) -> dict:
        """Atomically claim a task. If another live agent holds it you get claimed=false and who holds it."""
        return await run(hm.claim_task, actor(ctx), task_id)

    @mcp.tool()
    async def list_tasks(status: str | None = None, ctx: Context = None) -> list[dict]:
        """List shared tasks. status: open | claimed | handed_off | done."""
        return await run(hm.list_tasks, actor(ctx), status=status)

    @mcp.tool()
    async def complete_task(task_id: str, summary: str = "", ctx: Context = None) -> dict:
        """Mark a task done with a short summary of the result."""
        return await run(hm.complete_task, actor(ctx), task_id, summary)

    @mcp.tool()
    async def handoff(task_id: str, summary: str, next_steps: list[str] | None = None, to_agent: str | None = None,
                      to_role: str | None = None, carry: list[str] | None = None, ctx: Context = None) -> dict:
        """Hand a task to another agent (to_agent), a role (to_role, e.g. "reviewer"), or anyone (neither).
        `carry` lists fact/procedure/episode ids the next agent should see."""
        return await run(hm.handoff, actor(ctx), task_id, summary, next_steps=next_steps, to_agent=to_agent,
                         to_role=to_role, carry=carry)

    @mcp.tool()
    async def inbox(ctx: Context = None) -> list[dict]:
        """Pending handoffs addressed to you, your role, or anyone."""
        return await run(hm.inbox, actor(ctx))

    @mcp.tool()
    async def accept_handoff(handoff_id: str, ctx: Context = None) -> dict:
        """Accept a handoff and claim its task."""
        return await run(hm.accept_handoff, actor(ctx), handoff_id)

    @mcp.tool()
    async def team_status(ctx: Context = None) -> list[dict]:
        """Which agents are active right now, what tasks they hold and which files they are editing."""
        return await run(hm.team_status, actor(ctx))

    @mcp.tool()
    async def briefing(ctx: Context = None) -> str:
        """A compact summary of what you should know: handoffs for you, active teammates, verified
        procedures, key facts and recent changes."""
        return (await run(hm.briefing, actor(ctx)))["text"]

    return mcp


def run_stdio() -> None:
    settings = Settings.from_env()
    build_server(Hivemind(settings), settings).run("stdio")
