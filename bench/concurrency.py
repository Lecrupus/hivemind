"""Concurrency benchmark: many agents reading and writing memory at once.

Measures, against a real FalkorDB:
  1. Throughput and latency of a mixed agent workload (70% recall, 20% remember,
     10% learn) with N concurrent agents, all in ONE shared graph vs spread over
     TEN tenant graphs on the same instance.
  2. A claim race: 100 agents claim the same task at the same instant, 20 times.
     Correct coordination means exactly one winner every time.

Embeddings use the deterministic hash embedder so the numbers measure the
database and Hivemind's queries, not the ONNX model.

    uv run python bench/concurrency.py [--agents 10 50 100] [--ops 30]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import platform
import random
import statistics
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from hivemind.config import Settings
from hivemind.core import Actor, Hivemind
from hivemind.embeddings import HashEmbedder

OUT = Path(__file__).resolve().parent.parent / "src" / "hivemind" / "web" / "bench" / "concurrency.json"
MODULES = ["auth", "payments", "ledger", "billing", "search", "notifications", "dashboard", "api", "workers", "db"]
THINGS = ["retries", "timeouts", "idempotency keys", "migrations", "feature flags", "rate limits", "caching",
          "logging", "error handling", "pagination", "webhooks", "tests", "fixtures", "env vars", "secrets"]
VERBS = ["needs", "relies on", "must not skip", "configures", "validates", "owns", "documents", "breaks without"]
QUERIES = ["how do I run the tests", "what does payments rely on", "rate limits in the api", "how are migrations run",
           "webhook validation rules", "auth token caching", "what breaks without fixtures", "ledger idempotency"]


def statement(rng: random.Random) -> str:
    m, t, v = rng.choice(MODULES), rng.choice(THINGS), rng.choice(VERBS)
    return f"The {m} module {v} {t} (see src/{m}/{t.replace(' ', '_')}.py) note {rng.randint(0, 10**6)}"


def seed(hm: Hivemind, ws: str, facts: int, rng: random.Random) -> None:
    a = Actor(workspace=ws, user="seed", agent_id="seed@bench", session_id=f"s_seed_{ws}")
    hm.start_session(a, a.session_id)
    for _ in range(facts):
        hm.learn(a, statement(rng))
    for i in range(facts // 5):
        hm.record_procedure(a, f"Procedure {i}: run {rng.choice(MODULES)} {rng.choice(THINGS)}",
                            [f"make {rng.choice(MODULES)}", "uv run pytest -q"])


def _worker(args) -> tuple[list[float], int, float, float]:
    """One OS process running a slice of the agents as threads, with its own FalkorDB client."""
    name, workspaces, agent_ids, ops, barrier = args
    hm = Hivemind(Settings.from_env(embedder="hash"), embedder=HashEmbedder())
    actors = {}
    for i in agent_ids:  # set-up (sessions, connections) happens before the clock starts
        a = Actor(workspace=workspaces[i % len(workspaces)], user=f"u{i}", agent_id=f"bench-{i}@u{i}",
                  session_id=f"s_bench_{name}_{i}")
        hm.start_session(a, a.session_id)
        actors[i] = a
    barrier.wait()
    started = time.time()
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()

    def agent(i: int):
        nonlocal errors
        rng = random.Random(i)
        a = actors[i]
        local = []
        for _ in range(ops):
            r = rng.random()
            t0 = time.perf_counter()
            try:
                if r < 0.7:
                    hm.recall(a, rng.choice(QUERIES), k=5)
                elif r < 0.9:
                    hm.remember(a, f"$ pytest -q  # run {rng.randint(0, 10**6)}", kind="action")
                else:
                    hm.learn(a, statement(rng))
            except Exception:
                with lock:
                    errors += 1
                continue
            local.append((time.perf_counter() - t0) * 1000)
        with lock:
            latencies.extend(local)

    with ThreadPoolExecutor(max_workers=len(agent_ids)) as pool:
        list(pool.map(agent, agent_ids))
    return latencies, errors, started, time.time()


def run_scenario(name: str, workspaces: list[str], agents: int, ops: int, procs: int) -> dict:
    """Agents are spread over `procs` processes so the Python client (GIL) is not the bottleneck."""
    procs = max(1, min(procs, agents))
    slices = [list(range(agents))[k::procs] for k in range(procs)]
    with multiprocessing.Manager() as manager:
        barrier = manager.Barrier(procs)  # every process is connected and ready before timing starts
        with ProcessPoolExecutor(max_workers=procs) as pool:
            results = list(pool.map(_worker, [(name, workspaces, sl, ops, barrier) for sl in slices]))
    wall = max(r[3] for r in results) - min(r[2] for r in results)
    latencies = sorted(x for r in results for x in r[0])
    errors = sum(r[1] for r in results)
    q = statistics.quantiles(latencies, n=100) if len(latencies) > 2 else [0] * 99
    return {"name": name, "agents": agents, "graphs": len(workspaces), "processes": procs, "ops": len(latencies),
            "errors": errors, "seconds": round(wall, 2), "ops_per_s": len(latencies) / wall,
            "p50_ms": statistics.median(latencies), "p95_ms": q[94], "p99_ms": q[98]}


def claim_race(hm: Hivemind, ws: str, agents: int, trials: int) -> dict:
    exactly_one = 0
    owner = Actor(workspace=ws, user="lead", agent_id="lead@bench", session_id="s_lead")
    hm.start_session(owner, owner.session_id)
    racers = [Actor(workspace=ws, user=f"r{i}", agent_id=f"racer-{i}@r{i}", session_id=f"s_racer_{i}") for i in range(agents)]
    for a in racers:
        hm.start_session(a, a.session_id)
    for _ in range(trials):
        task = hm.create_task(owner, f"Hotfix {random.randint(0, 10**6)}")
        barrier = threading.Barrier(agents)
        wins = []

        def go(a: Actor):
            barrier.wait()
            if hm.claim_task(a, task["id"]).get("claimed"):
                wins.append(a.agent_id)

        threads = [threading.Thread(target=go, args=(a,)) for a in racers]
        [t.start() for t in threads]
        [t.join() for t in threads]
        exactly_one += len(wins) == 1
    return {"agents": agents, "trials": trials, "exactly_one_winner": exactly_one}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, nargs="+", default=[10, 50, 100])
    ap.add_argument("--ops", type=int, default=30)
    ap.add_argument("--facts", type=int, default=200)
    ap.add_argument("--procs", type=int, default=max(2, (os.cpu_count() or 4) // 2),
                    help="load-generator processes (the Python client is GIL-bound)")
    args = ap.parse_args()

    settings = Settings.from_env(embedder="hash")
    hm = Hivemind(settings, embedder=HashEmbedder())
    rng = random.Random(7)
    shared = ["bench-shared"]
    tenants = [f"bench-t{i}" for i in range(10)]
    for ws in shared + tenants + ["bench-race"]:
        for g in hm.db.list_graphs():
            if g == f"hivemind_{ws}" or g.startswith(f"hivemind_{ws}__"):
                hm.db.delete_graph(g)
    print("seeding...")
    seed(hm, shared[0], args.facts, rng)
    for ws in tenants:
        seed(hm, ws, args.facts // 4, rng)

    scenarios = []
    for n in args.agents:
        for label, wss in (("1 shared graph", shared), ("10 tenant graphs", tenants)):
            r = run_scenario(f"{n} agents · {label}", wss, n, args.ops, args.procs)
            print(f"{r['name']:<32} {r['ops_per_s']:8.0f} ops/s  p50 {r['p50_ms']:6.1f} ms  p95 {r['p95_ms']:6.1f} ms  errors {r['errors']}")
            scenarios.append(r)
    race = claim_race(hm, "bench-race", agents=100, trials=20)
    print(f"claim race: exactly one winner in {race['exactly_one_winner']}/{race['trials']} trials of {race['agents']} agents")

    info = hm.db.redis.info("server")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "machine": f"{platform.system()} {platform.release()}, {os.cpu_count()} CPUs, FalkorDB on Redis {info.get('redis_version')} (Docker)",
        "description": f"Mixed workload per agent: 70% recall (vector + full-text + graph expansion), 20% remember, 10% learn. "
                       f"Load generated from {args.procs} processes. Each recall runs ~8 FalkorDB queries.",
        "scenarios": scenarios, "race": race,
    }, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
