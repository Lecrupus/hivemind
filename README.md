# Hivemind

**Your AI coding agents learn from each other's mistakes and don't step on each other's toes.**

Hivemind is a shared, time-aware memory and coordination layer for teams of AI agents (Claude Code, Cursor, Codex or your own), stored as a graph in **FalkorDB**. Agents connect over MCP and Claude Code hooks. From then on, every session starts with what the team already knows, and every mistake is made only once.

Built for **Graph Hacks** (WeMakeDevs × FalkorDB), **Track 2: Agent Memory and Coordination**.

**[Demo video (2 min)](https://github.com/Lecrupus/hivemind/releases/tag/v0.1.0)** · [Architecture and judge Q&A](ARCHITECTURE.md) · [Deploy your own, free](#deploy)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Lecrupus/hivemind)

![Map: agents, their work, what they learned and the topics it touches](docs/img/relationship-map.png)

---

## The problem

Teams now run several AI agents on the same codebase, and none of them remembers anything:

- Agent A burns a long detour discovering that the tests need `docker compose up -d db`. An hour later, Agent B rediscovers it from scratch.
- Two agents edit `refunds.py` at the same time without knowing it.
- A decision ("refunds go through `LedgerService.reverse()`") lives in one chat transcript and dies with it.
- When the team changes its mind ("we moved from pnpm to bun"), stale memory keeps resurfacing.

## What Hivemind does

| | What happens | Where in the code |
|---|---|---|
| **Learns how-tos by watching** | When a command fails, the agent changes something, and the same command then succeeds, Hivemind turns those steps into a **Procedure** automatically. No tool call is needed. | `hooks.py` → `post_tool` |
| **Recall at the moment of failure** | When any agent hits an error the team has seen before, the verified fix is attached to the error itself, with who learned it and how often it worked. | `hooks.py` → `known_fix` |
| **Live coordination** | It warns an agent before it edits a file another live session is editing. One query does an atomic task claim (100 agents race, exactly one wins). Handoffs carry the facts and procedures the next agent needs. | `queries.py` → `CLAIM_TASK`, `FILE_CONFLICTS`, `CREATE_HANDOFF` |
| **Facts that know about time** | Facts are never overwritten. A new value **supersedes** the old one, which is kept with `valid_to`. *"What did we believe last Tuesday?"* is one parameter. | `queries.py` → `valid_at`, `SUPERSEDE_FACT` |
| **Every answer is explainable** | `why(id)` walks the graph from a memory back to the episode, session, agent and human it came from, what it replaced, and which handoffs carried it. Recall results say *why they ranked* (semantic, keyword, graph hops). | `queries.py` → `WHY`, `PROVENANCE` |
| **Private and team memory** | Each user has a private graph. Notes can be promoted to the team graph on purpose. Each workspace (team or tenant) is its own graph on the same FalkorDB instance. | `db.py`, `core.py` → `promote` |
| **Graph algorithms do real work** | PageRank ranks which parts of the codebase matter; connected components plus label propagation group knowledge into topics; shortest path explains how two things relate. | `core.py` → `consolidate`, `connect` |

It also says **"not in the graph"** instead of guessing when it doesn't know something.

**Measured results:**
- **On real Claude Code:** when a team rule lived only in a teammate's earlier session, runs went from **0/2 correct without Hivemind to 2/2 with it**, at about 23% higher cost.
- **At 100 concurrent agents:** about 1,300 memory operations a second, with exactly one winner in 20/20 claim races.
- **When the knowledge was also in the repo:** no difference. Details and both tables are in [Benchmarks](#benchmarks).

## Track 2 coverage

| Track 2 asks for | Hivemind |
|---|---|
| Episodic, semantic and procedural memory | `Episode` (what happened, in order via `NEXT`), `Fact` (bi-temporal, deduplicated, superseded not overwritten), `Procedure` (steps + success/failure counts, revisions via `REVISES`) |
| Persistent conversation history | Hooks record every prompt and reply as episodes chained per session; `history()` searches across all sessions and agents |
| Shared state and handoffs between agents | `Task` claims, `Handoff` nodes that `CARRY` facts and procedures, live presence via `TOUCHED`, the `team_status` and `inbox` tools, and a briefing injected at every session start |
| High-concurrency reads and writes | Read queries use `GRAPH.RO_QUERY` on snapshots. Writes are single atomic queries, so FalkorDB's per-graph write serialisation makes claims race-free. Benchmarked at 100 concurrent agents (below). |
| Separate memory per user or tenant | One graph per workspace plus one private graph per user, all on one FalkorDB instance (`hivemind_<workspace>`, `hivemind_<workspace>__<user>`) |

## See it in 60 seconds

Run it yourself (or [deploy it free on Render](#deploy)):

```bash
docker compose up -d
```

Open http://localhost:8765 and press **Play the demo**. Three agents (Claude Code, Cursor, Codex) work on one repo, and the captions narrate what Hivemind does:

1. Alice's agent hits a failing test, fixes it, and Hivemind **learns the procedure automatically**.
2. Bob's agent is about to edit the same file, and **gets warned**.
3. The CI agent hits the same failure and **gets Alice's fix at the moment of failure**.
4. Alice **hands off** her task to "whoever is the reviewer", carrying the decision and the procedure.
5. The team switches from pnpm to bun. The old fact is **superseded, not deleted**; drag *Time travel* to see last week.
6. Three agents **race** for a hotfix task; exactly one wins.
7. Bob's private note gets **promoted** to the team. **Consolidation** runs PageRank and community detection.

Then select any memory and press **Why do we know this?**

| Provenance | Board |
|---|---|
| ![Provenance trail](docs/img/provenance.png) | ![Board: tasks by status, with handoffs](docs/img/task-board.png) |

## Use it with your own agents

```bash
# 1. FalkorDB + the Hivemind server (dashboard, REST, MCP over HTTP)
docker run -d -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest
uv sync && uv run hivemind serve            # http://127.0.0.1:8765

# 2. Connect a project (writes .mcp.json + Claude Code hooks)
uv run hivemind install claude-code --dir path/to/your/repo --workspace payments-api --user alice
uv run hivemind install cursor      --dir path/to/your/repo --workspace payments-api --user bob
uv run hivemind install codex       --workspace payments-api --user ci   # prints the config.toml block
```

Two agents on one machine can have different identities. Set the agent id in each terminal before starting the agent:

```bash
export HIVEMIND_AGENT_ID=claude-code@alice-review
```

`uv run hivemind doctor` checks FalkorDB, the server and the hook command.

### MCP tools (22)

`recall` · `learn` · `supersede` · `forget` · `promote` · `why` · `timeline` · `connect` · `remember` · `history` · `record_procedure` · `find_procedure` · `report_outcome` · `create_task` · `claim_task` · `list_tasks` · `complete_task` · `handoff` · `inbox` · `accept_handoff` · `team_status` · `briefing`

Agents never write Cypher. Each tool calls a fixed, parameterised query from [`queries.py`](src/hivemind/queries.py).

### Claude Code hooks (7)

| Hook | Does |
|---|---|
| `SessionStart` | Registers the session and injects the team briefing: handoffs for you, live teammates, verified procedures, key facts, recent changes |
| `UserPromptSubmit` | Stores the prompt (conversation history) and injects memory relevant to it |
| `PreToolUse` (edits) | Warns if another live session touched the same file in the last 30 minutes (`HIVEMIND_CONFLICT_MODE=warn\|ask\|off`) |
| `PostToolUse` | Tracks edited files; mines procedures from fail → fix → success |
| `PostToolUseFailure` | Stores the error and injects the team's known fix |
| `Stop` / `SessionEnd` | Stores the reply; closes the session |

The hook client is stdlib-only and calls the running server, so a hook takes 0.3–0.5 s. If the server is down, hooks exit silently and never block the agent.

## The graph model

```mermaid
graph LR
  User((User)) --- Agent((Agent))
  Session -->|RUN_BY| Agent
  Episode -->|IN_SESSION| Session
  Episode -->|NEXT| Episode
  Episode -->|MENTIONS| Entity
  Fact -->|LEARNED_FROM| Episode
  Fact -->|LEARNED_BY| Agent
  Fact -->|ABOUT| Entity
  Fact -->|SUPERSEDES| Fact
  Procedure -->|LEARNED_FROM| Episode
  Procedure -->|FOR| Entity
  Procedure -->|REVISES| Procedure
  Procedure -->|USED_IN| Session
  Task -->|CLAIMED_BY| Agent
  Handoff -->|OF| Task
  Handoff -->|FROM / TO| Agent
  Handoff -->|CARRIES| Fact
  Session -->|TOUCHED| Entity
  Entity -->|RELATES_TO| Entity
  Entity -->|IN_TOPIC| Topic
```

- **Graphs:** `hivemind_<workspace>` holds the team's memory. `hivemind_<workspace>__<user>` holds each person's private memory.
- **Bi-temporal facts:** `valid_from` and `valid_to` say when a fact was true; `recorded_at` says when the team learned it.
- **Indexes:**
  - range indexes on every `id`
  - vector indexes (384-dimension, cosine) on `Fact`, `Procedure` and `Episode`
  - full-text indexes on fact statements, episode text and procedure goals

## The Cypher that does the work

All queries live in [`src/hivemind/queries.py`](src/hivemind/queries.py) (about 60, all parameterised). A few that carry the product:

**Atomic task claim.** FalkorDB runs writes to one graph one at a time, so this single query is a race-free compare-and-set:

```cypher
MATCH (t:Task {id: $task_id})
WHERE t.status IN ['open', 'handed_off']
   OR (t.status = 'claimed' AND (t.claimed_by = $agent_id OR t.heartbeat < $stale_before))
MATCH (a:Agent {id: $agent_id})
OPTIONAL MATCH (t)-[old:CLAIMED_BY]->() DELETE old
WITH DISTINCT t, a
SET t.status = 'claimed', t.claimed_by = $agent_id, t.heartbeat = $now
CREATE (t)-[:CLAIMED_BY {at: $now}]->(a)
RETURN t.id AS id
```

**Semantic recall that respects time.** Vector search, then keep only facts that were true and known at `$as_of`:

```cypher
CALL db.idx.vector.queryNodes('Fact', 'embedding', $k, vecf32($embedding)) YIELD node AS f, score
WHERE f.recorded_at <= $as_of AND f.valid_from <= $as_of
  AND (f.valid_to IS NULL OR f.valid_to > $as_of) AND NOT f.status IN ['retracted', 'promoted']
RETURN f.id AS id, f.statement AS statement, 1.0 - score AS sim
```

**Graph expansion.** Facts about the entities named in a query, and about their neighbours:

```cypher
MATCH (seed:Entity) WHERE seed.id IN $entity_ids
MATCH path = (seed)-[:RELATES_TO*0..1]-(x:Entity)<-[:ABOUT]-(f:Fact)
WITH f, min(length(path)) AS hops, collect(DISTINCT x.name) AS via
RETURN f.id, f.statement, hops, via
```

**Who else is editing this file right now?**

```cypher
MATCH (x:Entity {id: $entity_id})<-[r:TOUCHED]-(s:Session)-[:RUN_BY]->(a:Agent)
WHERE r.at >= $since AND s.id <> $session_id AND s.status = 'active'
RETURN a.id AS agent_id, r.at AS at
```

**Graph algorithms used as memory tools:**
- `algo.pageRank('Entity', 'RELATES_TO')` gives each part of the codebase a centrality score, which feeds fact importance.
- `algo.WCC` groups entities into topics, and `algo.labelPropagation` splits large components into smaller topics.
- `algo.SPpaths` powers `connect(a, b)`, which explains how two memories relate.

Recall combines three signals: vector similarity, full-text (RediSearch, with stemming) and graph hops. Each result carries its score breakdown.

## Benchmarks

### Concurrency (`bench/concurrency.py`)

Each agent ran a mixed workload: 70% recall (vector, full-text and graph expansion, about 8 FalkorDB queries each), 20% remember and 10% learn. FalkorDB ran in Docker on a 24-core Windows laptop, with load generated from 12 processes.

| Scenario | Ops/s | p50 | p95 | Errors |
|---|---|---|---|---|
| 10 agents · 1 shared graph | 638 | 16.7 ms | 22.8 ms | 0 |
| 10 agents · 10 tenant graphs | 660 | 16.3 ms | 22.6 ms | 0 |
| 50 agents · 1 shared graph | 871 | 29.6 ms | 135.9 ms | 0 |
| 50 agents · 10 tenant graphs | 857 | 57.3 ms | 97.5 ms | 0 |
| 100 agents · 1 shared graph | 1,105 | 22.3 ms | 160.7 ms | 0 |
| 100 agents · 10 tenant graphs | **1,301** | 62.3 ms | 146.0 ms | 0 |

- **Claim race:** 100 agents claimed the same task at the same instant, 20 times, and there was **exactly one winner in 20/20 trials**.
- **One graph per tenant** gave 18% more throughput at 100 agents, because writes to different graphs don't queue behind each other.

### With vs without memory, on real Claude Code (`bench/ab_claude_code.py`)

Each run copies [`demo/sample-repo`](demo/sample-repo) (a small payments service) to a fresh folder. The script then runs `claude -p` (Claude Code, Claude Opus 5.5) on one task: *add `apply_discount`, follow the team's conventions, make the suite pass*. It records turns, time and cost, and hidden acceptance checks verify correctness. The "with" runs start from the memory an earlier teammate's session left behind. There are 2 runs per variant in each of two scenarios.

**1. Knowledge only in team memory** (`--scenario memory-only`). A finance decision lives only in a teammate's earlier session: discounts are capped at 50% and round *down*, in the shop's favour. The repo's conventions doc is removed from the copy, so nothing in the code states these rules. The test trap (`PAYMENTS_ENV=test`) is still there.

| | Turns | Wall time | Cost | Correct (hidden checks) |
|---|---|---|---|---|
| Without Hivemind | 5, 4 (avg 4.5) | 37 s, 32 s (avg 35 s) | $0.23, $0.21 (avg $0.22) | **0/2** |
| With Hivemind | 5, 9 (avg 7) | 41 s, 62 s (avg 52 s) | $0.24, $0.30 (avg $0.27) | **2/2** |

**Reading:**
- Without memory, both runs did the sensible thing from the code: they rounded half-up with the existing `round_cents` helper, which fails the team's actual rule.
- With Hivemind, both runs applied the cap and the round-down rule. One told the user the rules came from the team's shared notes and asked them to confirm.
- **Being right cost more:** on average 2.5 more turns and $0.05 more per run, because the agent read and acted on more context.
- Two runs per variant is a small sample. The correctness difference is the signal; the cost difference is a real trade-off.

**2. Knowledge also in the repo** (`--scenario in-repo`). Every rule is also written in the repo: the error message names the ledger, and `docs/CONVENTIONS.md` states the rounding rule.

| | Turns | Wall time | Cost | Correct (hidden checks) |
|---|---|---|---|---|
| Without Hivemind | 4, 6 (avg 5) | 37 s, 45 s (avg 41 s) | $0.41, $0.24 (avg $0.33) | 2/2 |
| With Hivemind | 6, 5 (avg 5.5) | 37 s, 35 s (avg 36 s) | $0.43, $0.22 (avg $0.33) | 2/2 |

**Reading: no meaningful difference.** Opus 5.5 recovered everything from the repo on its own, so memory had nothing left to save. The wall-time gap is noise at 2 runs.

**Takeaway:** on a small repo, a strong model rediscovers what's written down. Shared memory pays off on what *isn't* written down: decisions, a teammate's findings, rules that live in people's heads. There it was the difference between a wrong answer and a right one.

Reproduce:

```bash
uv run python bench/ab_claude_code.py --claude path/to/claude --scenario memory-only --runs 2
uv run python bench/ab_claude_code.py --claude path/to/claude --scenario in-repo --runs 2
```

## Tests

```bash
uv run pytest      # 18 tests against a real FalkorDB
```

The tests cover:
- deduplication
- replacing a fact by key, and time travel back to its old value
- saying "not in the graph" honestly
- strengthening and revising procedures
- the 25-agent claim race
- handoffs routed by role
- private isolation and promotion
- provenance
- hard delete of derived memories
- procedure learning through hooks and serving the fix
- conflict warnings
- the session briefing

## Deploy

**One click, free, no database account** ([`render.yaml`](render.yaml)). Press **Deploy to Render** above and sign in with GitHub. Render builds `deploy/standalone/Dockerfile`, a single container running FalkorDB and Hivemind together (about 310 MB of RAM, within the free tier's 512 MB), and generates `HIVEMIND_API_KEY`. The demo workspace is seeded at start. Free instances sleep after 15 idle minutes, and the first visit after that takes about a minute.

The same container runs on any Docker host:

```bash
docker build -f deploy/standalone/Dockerfile -t hivemind-standalone .
docker run -p 7860:7860 -e HIVEMIND_API_KEY=change-me hivemind-standalone
```

Memory resets when that container restarts, so it suits demos. For a team, keep FalkorDB separate and durable:

- **Docker Compose:** `docker compose up -d` (FalkorDB with a data volume + the server).
- **Render + FalkorDB Cloud:** in `render.yaml`, set `dockerfilePath: ./Dockerfile` and add `HIVEMIND_FALKORDB_URL` with your FalkorDB Cloud instance's `redis://default:PASSWORD@HOST:PORT`.

To point agents at a deployed server, set `HIVEMIND_API_KEY` in your shell, then run `hivemind install claude-code --url https://YOUR-HOST`. The hooks and `.mcp.json` send the key as a bearer token.

## Privacy and safety

- **Secrets are redacted before storage:** API keys, GitHub/AWS/Slack tokens, JWTs, private keys, `password=…`, and credentials in URLs.
- **`forget(id, hard=True)` deletes a memory** and anything derived only from it.
- **Private memory never reaches the team** unless promoted.
- **`HIVEMIND_API_KEY`** protects `/mcp` and `/api/hook` on public deployments. The dashboard's "Play the demo" can only touch the `demo` workspace.
- **Agents can't run arbitrary Cypher.** They only call fixed, parameterised queries.

## Limitations (honest)

- **The dashboard's read endpoints are unauthenticated.** Put the server behind your own auth before storing private data on a public host.
- **Procedure mining is a heuristic.** It needs a failing command to later succeed in the same session. Steps the agent took by editing files (rather than running commands) aren't captured; agents record those with `record_procedure`.
- **Fact extraction is agent-driven**, through `learn` and the hooks. No extra LLM call is made, which keeps it key-free and cheap, but it means memory is only as good as what agents choose to record.
- **The hooks are Claude Code's.** Cursor and Codex get the full MCP tool set but not the automatic hooks.

## Project layout

```
src/hivemind/
  queries.py     the Cypher catalogue (graph model documented at the top)
  core.py        memory + coordination engine (one class, every operation)
  hooks.py       Claude Code hook handlers (procedure mining, known-fix recall, conflicts)
  mcp_server.py  22 MCP tools (streamable HTTP or stdio)
  api.py         FastAPI server: dashboard, REST, hook endpoint, MCP, live events (SSE)
  demo.py        the scripted multi-agent scenario behind "Play the demo"
  web/           the dashboard (vanilla JS, no build step)
bench/           concurrency benchmark, Claude Code A/B
tests/           integration tests against FalkorDB
deploy/          self-contained container (FalkorDB + server) used by render.yaml
demo/sample-repo the payments repo used by the A/B benchmark
```

## Built with

FalkorDB (graph, vector, full-text, algorithms, multi-graph), the MCP Python SDK, FastAPI, and fastembed (`BAAI/bge-small-en-v1.5`, local, no API key).

## AI assistance disclosure

This project was built during the hackathon with **Claude Code (Claude Opus 5.5)** as a pair programmer. Claude wrote much of the code, under my direction and review:
- the product idea
- the Track 2 framing
- design decisions
- testing
- the demo and benchmarks

The demo video's narration is AI-generated (Kokoro TTS, run locally).

I can explain every part of the graph model, the queries and the architecture; see [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT
