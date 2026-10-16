"""Integration tests against a real FalkorDB (skipped if it isn't running)."""

import threading
import time

from hivemind import hooks
from hivemind.text import now_ms


def test_duplicate_fact_is_reinforced_not_duplicated(hm, agent):
    alice, bob = agent("alice"), agent("bob")
    first = hm.learn(alice, "The API uses FastAPI on Python 3.12")
    again = hm.learn(bob, "The API uses FastAPI on Python 3.12")
    assert again["status"] == "reinforced" and again["id"] == first["id"]
    assert again["confidence"] > 0.8


def test_keyed_fact_supersedes_and_time_travel_sees_the_old_value(hm, agent):
    alice = agent("alice")
    old = hm.learn(alice, "The frontend uses pnpm", key="frontend.package_manager")
    time.sleep(0.02)
    before_change = now_ms()
    time.sleep(0.02)
    new = hm.learn(alice, "The frontend uses bun", key="frontend.package_manager")
    assert new["superseded"][0]["id"] == old["id"]

    now_ids = {r["id"] for r in hm.recall(alice, "frontend package manager pnpm bun", bump=False)["results"]}
    then_ids = {r["id"] for r in hm.recall(alice, "frontend package manager pnpm bun", as_of=before_change,
                                           bump=False)["results"]}
    assert new["id"] in now_ids and old["id"] not in now_ids
    assert old["id"] in then_ids and new["id"] not in then_ids


def test_recall_admits_when_nothing_is_known(hm, agent):
    r = hm.recall(agent("alice"), "kubernetes ingress annotations", bump=False)
    assert r["results"] == []
    assert "Not in the graph" in r["summary"]


def test_procedure_same_steps_reinforce_different_steps_revise(hm, agent):
    alice, bob = agent("alice"), agent("bob")
    p = hm.record_procedure(alice, "Run the backend tests", ["docker compose up -d db", "uv run pytest -q"])
    same = hm.record_procedure(bob, "Run the backend tests", ["docker compose up -d db", "pytest -q"])
    assert same["status"] == "reinforced" and same["id"] == p["id"] and same["success_count"] == 2
    other = hm.record_procedure(bob, "Run the backend tests", ["make test"])
    assert other["status"] == "created" and other["revises"] == p["id"]


def test_claim_race_has_exactly_one_winner(hm, agent):
    lead = agent("lead")
    racers = [agent(f"r{i}") for i in range(25)]
    task = hm.create_task(lead, "Hotfix the retry bug")
    barrier = threading.Barrier(len(racers))
    wins = []

    def go(a):
        barrier.wait()
        if hm.claim_task(a, task["id"])["claimed"]:
            wins.append(a.agent_id)

    threads = [threading.Thread(target=go, args=(a,)) for a in racers]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(wins) == 1


def test_handoff_reaches_role_with_carried_context(hm, agent):
    alice, bob = agent("alice"), agent("bob", "cursor", role="reviewer")
    fact = hm.learn(alice, "Refunds go through LedgerService.reverse()")
    task = hm.create_task(alice, "Add refund endpoint", claim=True)
    h = hm.handoff(alice, task["id"], "Needs edge-case tests", ["partial refunds"], to_role="reviewer", carry=[fact["id"]])
    inbox = hm.inbox(bob)
    assert inbox and inbox[0]["id"] == h["handoff_id"]
    assert inbox[0]["carried"][0]["id"] == fact["id"]
    assert hm.accept_handoff(bob, h["handoff_id"])["claim"]["claimed"]
    assert hm.inbox(agent("carol")) == []  # not a reviewer


def test_private_memory_is_isolated_until_promoted(hm, agent):
    alice, bob = agent("alice"), agent("bob")
    note = hm.learn(alice, "I suspect the ledger rounding is off by one cent", private=True)
    assert not any(r["id"] == note["id"] for r in hm.recall(bob, "ledger rounding cent", bump=False)["results"])
    promoted = hm.promote(alice, note["id"])
    team_id = promoted["team_fact"]["id"]
    assert any(r["id"] == team_id for r in hm.recall(bob, "ledger rounding cent", bump=False)["results"])


def test_why_explains_origin_and_replacement(hm, agent):
    alice = agent("alice")
    hm.learn(alice, "Deploys go through Jenkins", key="deploy.tool")
    new = hm.learn(alice, "Deploys go through GitHub Actions", key="deploy.tool")
    w = hm.why(alice, new["id"])
    text = " ".join(w["explanation"])
    assert "claude-code@alice" in text and "Jenkins" in text


def test_hard_delete_removes_facts_derived_only_from_the_episode(hm, agent):
    alice = agent("alice")
    ep = hm.remember(alice, "Customer email jane@example.com reported a refund bug", kind="note")
    fact = hm.learn(alice, "Refund bug affects partial refunds", episode_id=ep["id"])
    out = hm.forget(alice, ep["id"], hard=True)
    assert out["derived_deleted"] == 1
    assert "error" in hm.why(alice, fact["id"])


def test_hooks_learn_procedure_and_serve_it_to_the_next_agent(hm, agent):
    alice, ci = agent("alice"), agent("ci", "codex")
    err = 'E   psycopg.OperationalError: connection to server at "localhost", port 5432 failed: Connection refused'
    first = hooks.handle(hm, "post-tool-failure", {"tool_name": "Bash", "tool_input": {"command": "uv run pytest -q"},
                                                   "error": err}, alice)
    assert first == {}  # nothing known yet
    hooks.handle(hm, "post-tool", {"tool_name": "Bash", "tool_input": {"command": "docker compose up -d db"}}, alice)
    learned = hooks.handle(hm, "post-tool", {"tool_name": "Bash", "tool_input": {"command": "uv run pytest -q"}}, alice)
    assert "docker compose up -d db" in learned["hookSpecificOutput"]["additionalContext"]

    fix = hooks.handle(hm, "post-tool-failure", {"tool_name": "Bash", "tool_input": {"command": "pytest -q"},
                                                 "error": err}, ci)
    ctx = fix["hookSpecificOutput"]["additionalContext"]
    assert "docker compose up -d db" in ctx and "claude-code@alice" in ctx


def test_edit_conflict_warns_the_second_agent(hm, agent):
    alice, bob = agent("alice"), agent("bob", "cursor")
    hooks.handle(hm, "post-tool", {"tool_name": "Edit", "tool_input": {"file_path": "/repo/src/app.py"}}, alice)
    out = hooks.handle(hm, "pre-tool", {"tool_name": "Edit", "tool_input": {"file_path": "/repo/src/app.py"}}, bob)
    assert "claude-code@alice" in out["hookSpecificOutput"]["additionalContext"]
    mine = hooks.handle(hm, "pre-tool", {"tool_name": "Edit", "tool_input": {"file_path": "/repo/src/other.py"}}, bob)
    assert mine == {}


def test_session_start_briefing_lists_handoffs_and_procedures(hm, agent):
    alice, bob = agent("alice"), agent("bob", "cursor", role="reviewer")
    hm.record_procedure(alice, "Run the backend tests", ["docker compose up -d db", "pytest -q"])
    task = hm.create_task(alice, "Review refunds", claim=True)
    hm.handoff(alice, task["id"], "Please review", to_role="reviewer")
    out = hooks.handle(hm, "session-start", {"session_id": "s_bob_new"}, bob)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "Review refunds" in ctx and "docker compose up -d db" in ctx
