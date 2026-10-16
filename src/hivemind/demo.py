"""Scripted multi-agent scenario behind the dashboard's "Play the demo" button
(and `hivemind demo`).

It drives the real pipeline: agent turns go through hooks.handle() with the
same payloads Claude Code sends, and tool calls go through the Hivemind core,
so everything shown is what the product actually does. `demo.step` events
carry captions so viewers can follow along."""

from __future__ import annotations

import threading
import time

from . import hooks
from .core import Actor, Hivemind
from .db import shared_graph_name
from .text import now_ms

DAY = 86_400_000
CWD = "/work/payments-api"

_SHIFT_NODES = """
MATCH (n) WHERE coalesce(n.recorded_at, n.ts, n.created_at, n.started_at, 0) >= $since
SET n.recorded_at = CASE WHEN n.recorded_at IS NULL THEN NULL ELSE n.recorded_at - $d END,
    n.valid_from = CASE WHEN n.valid_from IS NULL THEN NULL ELSE n.valid_from - $d END,
    n.ts = CASE WHEN n.ts IS NULL THEN NULL ELSE n.ts - $d END,
    n.created_at = CASE WHEN n.created_at IS NULL THEN NULL ELSE n.created_at - $d END,
    n.started_at = CASE WHEN n.started_at IS NULL THEN NULL ELSE n.started_at - $d END,
    n.last_seen = CASE WHEN n.last_seen IS NULL THEN NULL ELSE n.last_seen - $d END,
    n.last_used = CASE WHEN n.last_used IS NULL THEN NULL ELSE n.last_used - $d END,
    n.updated_at = CASE WHEN n.updated_at IS NULL THEN NULL ELSE n.updated_at - $d END,
    n.ended_at = CASE WHEN n.ended_at IS NULL THEN NULL ELSE n.ended_at - $d END
"""
_SHIFT_EDGES = """
MATCH ()-[r]->() WHERE r.at >= $since
SET r.at = r.at - $d
"""


class Script:
    def __init__(self, hm: Hivemind, workspace: str, speed: float):
        self.hm, self.ws, self.speed = hm, workspace, speed

    def say(self, text: str, pause: float = 2.5) -> None:
        self.hm.events.publish(self.ws, "demo.step", text=text)
        self.wait(pause)

    def wait(self, seconds: float) -> None:
        time.sleep(seconds / self.speed)

    def agent(self, user: str, client: str, role: str | None = None) -> Actor:
        return Actor(workspace=self.ws, user=user, agent_id=f"{client}@{user}", client=client, role=role, cwd=CWD)

    def hook(self, event: str, a: Actor, **payload) -> dict:
        return hooks.handle(self.hm, event, {"session_id": a.session_id, "cwd": CWD, **payload}, a)

    def bash_ok(self, a: Actor, cmd: str) -> dict:
        return self.hook("post-tool", a, tool_name="Bash", tool_input={"command": cmd},
                         tool_response={"stdout": "ok", "stderr": ""})

    def bash_fail(self, a: Actor, cmd: str, error: str) -> dict:
        return self.hook("post-tool-failure", a, tool_name="Bash", tool_input={"command": cmd}, error=error)

    def edit(self, a: Actor, path: str) -> dict:
        out = self.hook("pre-tool", a, tool_name="Edit", tool_input={"file_path": f"{CWD}/{path}"})
        self.hook("post-tool", a, tool_name="Edit", tool_input={"file_path": f"{CWD}/{path}"})
        return out

    def backdate(self, since: int, days: float) -> None:
        g = shared_graph_name(self.ws)
        d = int(days * DAY)
        self.hm.db.query(g, _SHIFT_NODES, {"since": since, "d": d})
        self.hm.db.query(g, _SHIFT_EDGES, {"since": since, "d": d})


def reset_workspace(hm: Hivemind, workspace: str) -> None:
    prefix = shared_graph_name(workspace)
    for name in hm.db.list_graphs():
        if name == prefix or name.startswith(prefix + "__"):
            hm.db.delete_graph(name)
    hm._session_seen.clear()
    hooks._warned.clear()


def seed_history(s: Script) -> None:
    """Last week's memory, so the time-travel slider has a past to show."""
    hm = s.hm
    alice, bob, ci = s.agent("alice", "claude-code", "coder"), s.agent("bob", "cursor", "reviewer"), s.agent("ci", "codex", "ci")

    t = now_ms()
    hm.start_session(alice, "s_alice_mon")
    s.hook("prompt", alice, prompt="Set up the payments service: money handling, the API skeleton and the dashboard build")
    hm.learn(alice, "Money amounts are stored as integer cents; never use floats for currency", kind="convention",
             about=["src/payments/models.py"], confidence=0.95)
    hm.learn(alice, "The payments API is FastAPI on Python 3.12; run it locally with `uv run uvicorn app.main:app`",
             kind="config", about=["app/main.py"])
    hm.learn(alice, "The dashboard frontend uses pnpm", kind="config", key="frontend.package_manager",
             about=["dashboard/package.json"])
    hm.record_procedure(alice, "Run database migrations", ["uv run alembic upgrade head"], about=["alembic"])
    hm.record_procedure(alice, "Run database migrations", ["uv run alembic upgrade head"], about=["alembic"])
    hm.end_session(alice)
    s.backdate(t, 6)

    t = now_ms()
    hm.start_session(bob, "s_bob_wed")
    s.hook("prompt", bob, prompt="Review the refund rules with finance and write them down")
    hm.learn(bob, "Refunds over $500 need manual approval from finance before they are issued", kind="decision",
             about=["src/payments/refunds.py"], confidence=0.9)
    hm.learn(bob, "POST /refunds requires an Idempotency-Key header so client retries never double-refund",
             kind="gotcha", about=["src/payments/refunds.py", "src/payments/api.py"])
    hm.learn(bob, "Stripe webhooks must be signature-verified before any database write", kind="gotcha",
             about=["src/payments/webhooks.py"])
    hm.record_procedure(bob, "Deploy to staging", ["git push origin main", "gh workflow run deploy-staging.yml"],
                        about=["gh workflow"])
    task = hm.create_task(bob, "Add CSV export to the dashboard", about=["dashboard/src/export.ts"], claim=True)
    hm.complete_task(bob, task["id"], "Export button + streaming CSV endpoint shipped")
    hm.end_session(bob)
    s.backdate(t, 3)

    t = now_ms()
    hm.start_session(ci, "s_ci_thu")
    hm.learn(ci, "test_ledger_reconcile is flaky under parallel runs; run it with `pytest -p no:xdist`", kind="gotcha",
             about=["tests/test_ledger.py", "pytest"])
    hm.end_session(ci)
    s.backdate(t, 1)


def play(hm: Hivemind, workspace: str = "demo", speed: float = 1.0, reset: bool = True,
         history: bool = True) -> dict:
    if reset:
        reset_workspace(hm, workspace)
    s = Script(hm, workspace, speed)
    if history:
        s.say("Loading a week of team memory: conventions, decisions and how-tos from earlier sessions.", 1.5)
        seed_history(s)
        hm.consolidate(s.agent("system", "hivemind"))
    alice = s.agent("alice", "claude-code", "coder")
    bob = s.agent("bob", "cursor", "reviewer")
    ci = s.agent("ci", "codex", "ci")

    # 1. Alice's agent starts and hits a failure nobody has written down yet.
    alice.session_id = f"s_alice_{now_ms() % 100000}"
    s.say("Alice opens Claude Code. Hivemind briefs it with the team's memory.")
    s.hook("session-start", alice)
    s.hook("prompt", alice, prompt="Add a refund endpoint to the payments API, with tests")
    task = hm.create_task(alice, "Add refund endpoint to payments API",
                          "POST /refunds with idempotency and the $500 approval rule", about=["src/payments/refunds.py"],
                          claim=True)
    s.edit(alice, "src/payments/refunds.py")
    s.say("Alice's agent writes the endpoint, then runs the tests...", 1.5)
    first = s.bash_fail(alice, "uv run pytest -q", "E   psycopg.OperationalError: connection to server at \"localhost\" "
                "(127.0.0.1), port 5432 failed: Connection refused\n1 failed, 41 errors in 3.2s")
    s.say("Tests fail: Postgres isn't running. Nobody has recorded this yet, so there's no known fix.")
    s.bash_ok(alice, "docker compose up -d db")
    out = s.bash_ok(alice, "uv run pytest -q")
    learned = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
    s.say("Fixed. Hivemind watched fail -> fix -> success and learned the procedure on its own: "
          + (learned.split("': ")[-1].split(" [")[0] if learned else "start db, then pytest"), 3.5)

    # 2. Bob's agent starts in another editor and is warned off Alice's file.
    bob.session_id = f"s_bob_{now_ms() % 100000}"
    s.say("Bob opens Cursor on the same repo. His briefing shows Alice is live in refunds.py.")
    s.hook("session-start", bob)
    s.hook("prompt", bob, prompt="Tighten validation in the refunds module")
    warn = s.edit(bob, "src/payments/refunds.py")
    if warn:
        s.say("Bob's agent tries to edit refunds.py too. Hivemind warns it: Alice's agent is editing it right now.", 3)

    # 3. The CI agent hits the same failure, and gets the fix instantly.
    ci.session_id = f"s_ci_{now_ms() % 100000}"
    s.say("Meanwhile the Codex CI agent runs the suite on a fresh machine...")
    s.hook("session-start", ci)
    fix = s.bash_fail(ci, "pytest -q", "E   psycopg.OperationalError: connection to server at \"localhost\" "
                      "(127.0.0.1), port 5432 failed: Connection refused")
    if fix:
        s.say("Same error. This time Hivemind answers at the moment of failure with Alice's verified fix.", 3.5)
    s.bash_ok(ci, "docker compose up -d db")
    s.bash_ok(ci, "pytest -q")
    s.say("Codex follows it and passes first time. The procedure's success count goes up: memory that proves itself.", 3)

    # 4. Alice records a decision and hands off to a reviewer with context attached.
    d = hm.learn(alice, "Refunds must go through LedgerService.reverse(); never update balances directly",
                 kind="decision", about=["src/payments/refunds.py", "src/ledger/service.py"], confidence=0.9)
    s.say("Alice's agent records a design decision, with the file it came from as provenance.", 2)
    proc = hm.find_procedure(alice, "run the tests", k=1)
    h = hm.handoff(alice, task["id"], "Endpoint and happy-path tests done. Needs edge cases: partial refunds, >$500 approval.",
                   next_steps=["Add partial-refund tests", "Wire finance approval for >$500"], to_role="reviewer",
                   carry=[d["id"]] + [p["id"] for p in proc])
    hm.end_session(alice)
    s.say("Alice's session ends. She hands the task to whoever is the reviewer, carrying the decision and the test procedure.")
    inbox = hm.inbox(bob)
    if inbox:
        hm.accept_handoff(bob, inbox[0]["id"])
        s.say("Bob's agent finds it in its inbox, accepts, and picks up with full context.", 2.5)

    # 5. Knowledge changes: the old fact is superseded, not overwritten.
    hm.learn(bob, "The dashboard frontend uses bun (migrated from pnpm this week)", kind="config",
             key="frontend.package_manager", about=["dashboard/package.json"])
    s.say("Bob notes the frontend moved from pnpm to bun. The old fact is superseded and kept as history, "
          "so time travel still shows what the team believed last week.", 3.5)

    # 6. Coordination under contention: three agents race for one task.
    hot = hm.create_task(bob, "Hotfix: duplicate refund on client retry", about=["src/payments/refunds.py"])
    s.say("A hotfix task appears. Three agents try to claim it at the same instant...", 1.5)
    results: dict[str, dict] = {}
    racers = [s.agent("alice", "claude-code", "coder"), bob, ci]
    racers[0].session_id = f"s_alice_hotfix_{now_ms() % 100000}"
    barrier = threading.Barrier(len(racers))

    def race(a: Actor):
        barrier.wait()
        results[a.agent_id] = hm.claim_task(a, hot["id"])

    threads = [threading.Thread(target=race, args=(a,)) for a in racers]
    [t.start() for t in threads]
    [t.join() for t in threads]
    winner = next((k for k, v in results.items() if v.get("claimed")), "nobody")
    s.say(f"Exactly one wins: {winner}. FalkorDB serialises writes per graph, so the claim query is a race-free lock.", 3)

    # 7. Private memory, promoted to the team on purpose.
    p = hm.learn(bob, "Table-driven tests catch refund edge cases much faster", private=True)
    s.say("Bob keeps a personal note in his private graph: separate memory per user.", 2)
    hm.promote(bob, p["id"])
    s.say("He decides it's useful for everyone and promotes it to team memory.", 2)

    # 8. Graph algorithms keep memory organised.
    stats = hm.consolidate(s.agent("system", "hivemind"))
    s.say(f"Consolidation: PageRank scores what matters, label propagation groups knowledge into "
          f"{len(stats['topics'])} topics.", 2.5)
    hm.complete_task(bob, task["id"], "Edge cases covered; finance approval wired")
    s.say("Done. Click any memory and press Why? to trace exactly where it came from.", 1)
    hm.events.publish(workspace, "demo.finished", text="Demo complete")
    beats = {
        "first_failure_had_no_known_fix": not first,
        "procedure_learned_automatically": bool(learned),
        "conflict_warning_shown": bool(warn),
        "known_fix_served_to_ci": bool(fix),
        "handoff_accepted": bool(inbox),
        "race_winners": sum(1 for v in results.values() if v.get("claimed")),
    }
    return {"workspace": workspace, "beats": beats, "race": results}

