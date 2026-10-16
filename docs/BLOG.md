<!--
PUBLISHING CHECKLIST (delete this block before posting)
- Platform: Medium (both confirmed WeMakeDevs blog winners were on Medium); cross-post to dev.to and Hashnode with a canonical link.
- Tags: FalkorDB, AI Agents, Claude Code, Knowledge Graph, WeMakeDevs
- Links are filled in. On Medium, re-upload the images from docs/img/ where the image lines are.
- Read it aloud once and change anything that doesn't sound like you. Swap the opening scene for your own real version if you have one.
- Share on LinkedIn and X, tagging @WeMakeDevs and @FalkorDB, and put the link in the hackathon submission.
-->

# Your AI Agents Don't Learn From Each Other. I Gave Them a Shared Memory in FalkorDB.

*Hivemind, built for Graph Hacks: how it works, the Cypher behind it, and the benchmark that told me where team memory actually helps.*

![Hivemind's live map: agents, their work, what they learned, and the topics it touches.](img/relationship-map.png)
*Hivemind's live map: agents, their work, what they learned, and the topics it touches.*

Two AI agents. Same repo. One hour apart.

The first one runs the test suite, hits `psycopg.OperationalError: Connection refused`, pokes around, starts the Postgres container, and gets everything green. Then its session ends, and what it figured out goes with it.

An hour later a different agent runs the same tests, hits the same error, and starts from zero. Meanwhile a third agent is quietly editing the same file as the first one.

Each of my coding agents (Claude Code in the terminal, Cursor in the editor, Codex in CI) is brilliant on its own. Together they're a team with total amnesia and no way to talk to each other.

So for **Graph Hacks** (WeMakeDevs × FalkorDB, Track 2: Agent Memory and Coordination), I built **Hivemind**: one shared, time-aware memory for a team of AI agents, stored as a graph in FalkorDB. Agents connect through MCP and Claude Code hooks. From then on, every session starts with what the team already knows, and a mistake gets made once.

**Live demo:** [hivemind-9sus.onrender.com](https://hivemind-9sus.onrender.com) · **Code:** [github.com/Lecrupus/hivemind](https://github.com/Lecrupus/hivemind) · **Video:** [2-minute demo](https://github.com/Lecrupus/hivemind/releases/tag/v0.1.0)

This post walks through how it works, organised around the five things Track 2 asks agent memory to do. It shows the Cypher that does the real work, the bugs that bit me, and a benchmark whose first answer was "this doesn't help". That turned out to be the most useful thing I learned.

## A transcript is not a memory

The lazy version of agent memory is a longer prompt: dump the last conversation back in. It breaks the moment a team is involved, because the questions a team of agents needs answered aren't about text. They're about relationships:

- *Which agent learned this, in which session, from which error?*
- *What did we believe before we changed our minds?*
- *Who is editing this file right now?*
- *Which procedure fixed this error last time, and how often did it work?*

Each of those is a path through connected data, which makes it a graph problem. So Hivemind's memory is a FalkorDB graph:

```
User ◀─ACTS_FOR─ Agent ◀─RUN_BY─ Session ◀─IN_SESSION─ Episode ─NEXT─▶ Episode
                   ▲                                       ▲
              LEARNED_BY                              LEARNED_FROM
                   │                                       │
                 Fact ──ABOUT──▶ Entity ──IN_TOPIC──▶ Topic
                 │  └─SUPERSEDES─▶ Fact (the old belief, kept)
            Procedure ──FOR──▶ Entity          Handoff ─CARRIES─▶ Fact
```

- **Episodes** are what happened.
- **Facts** are what's true, and *when* it was true.
- **Procedures** are how to do something, with a record of whether each one worked.
- **Tasks** and **Handoffs** coordinate the agents.

Every fact points back at the episode it came from, so "why do we believe this?" always has an answer.

## 1. Episodic, semantic and procedural memory: it learns by watching

The part I'm proudest of needs no tool call at all.

Hivemind hooks into Claude Code. When a shell command fails, the session remembers which command failed. Commands that change something afterwards are collected (inspection commands like `ls` and `git status` are ignored). When the same command later succeeds, those steps become a **Procedure** every agent can see:

```
Run `pytest` successfully:  docker compose up -d db  ->  uv run pytest -q
(worked 2x, failed 0x; learned automatically from claude-code@alice's session)
```

Then the payoff. When *any* agent on the team hits that error again, the hook adds the fix to the error message itself, at the moment of failure:

```
Hivemind: your team has seen this failure before.
- Procedure 'Run `pytest` successfully' (worked 2x, by claude-code@alice):
  docker compose up -d db -> uv run pytest -q
- This error was hit before by claude-code@alice (1m ago).
```

Facts work differently from a notes file: **they're never overwritten.** When the team switches the frontend from pnpm to bun, the new fact *supersedes* the old one. The old fact gets a `valid_to` timestamp and stays in the graph. That makes "what did we believe last Tuesday?" one filter on the vector search:

```cypher
CALL db.idx.vector.queryNodes('Fact', 'embedding', $k, vecf32($embedding)) YIELD node AS f, score
WHERE f.recorded_at <= $as_of AND f.valid_from <= $as_of
  AND (f.valid_to IS NULL OR f.valid_to > $as_of)
RETURN f.statement, 1.0 - score AS similarity
```

FalkorDB's vector index, a temporal filter and the graph, in one query.

## 2. Persistent history: every answer can explain itself

Hooks record every prompt and reply as episodes, chained in order per session, so history survives across sessions and agents.

But the feature judges and teammates actually use is **"Why do we know this?"** One traversal walks from any memory back to the session, agent and person it came from. It also finds what the memory replaced, what replaced it, and which handoffs carried it.

![Selecting a memory lights up its trail back to the agent who learned it.](img/provenance.png)
*Selecting a memory lights up its trail back to the agent who learned it.*

Recall is explainable too. Each result says *why* it ranked, combining three signals:
- **semantic:** FalkorDB's vector index
- **keyword:** its full-text index
- **graph hops:** whether the memory is about something you named, or about one of its neighbours

And when nothing matches, Hivemind says *"not in the graph"* instead of handing back the least-bad guess.

## 3. Shared state and handoffs: agents that don't step on each other

Memory is half of Track 2. The other half is coordination:

- **Live presence.** Every edit records a `TOUCHED` edge from the session to the file. Before an agent edits a file, a hook asks the graph *"has another live session touched this in the last 30 minutes?"* If so, the agent is warned before the collision happens.
- **Handoffs that carry context.** When an agent stops, it hands the task to a specific agent, a role ("whoever is the reviewer"), or anyone. The handoff node `CARRIES` the exact facts and procedures the next agent needs, and they show up in that agent's briefing when its session starts.
- **A briefing at every session start:** handoffs waiting for you, which teammates are live and what they're editing, verified procedures, key facts, and what changed this week.

## 4. High-concurrency reads and writes: a race-free claim in one query

This is my favourite piece of FalkorDB behaviour. **FalkorDB runs writes to a graph one at a time.** So if the check and the update are in *one* query, that query is a compare-and-set, with no locks in my code:

```cypher
// simplified: the real query also releases a stale claim
MATCH (t:Task {id: $task_id})
WHERE t.status IN ['open', 'handed_off']
   OR (t.status = 'claimed' AND t.heartbeat < $stale_before)
MATCH (a:Agent {id: $agent_id})
SET t.status = 'claimed', t.claimed_by = $agent_id, t.heartbeat = $now
CREATE (t)-[:CLAIMED_BY {at: $now}]->(a)
RETURN t.id
```

I raced **100 agents for the same task, 20 times: exactly one winner in 20/20 trials.**

For throughput, every agent ran a mixed workload: 70% recall, 20% recording and 10% learning, with about eight FalkorDB queries per recall. FalkorDB ran in Docker on a laptop.

| Concurrent agents | Ops/s, one shared graph | Ops/s, 10 tenant graphs | Errors |
|---|---|---|---|
| 10 | 638 | 660 | 0 |
| 50 | 871 | 857 | 0 |
| 100 | 1,105 | **1,301** | 0 |

That's several thousand graph queries a second at 100 agents, with zero errors.

## 5. Separate memory per user and tenant: one graph each

Every workspace (a team or tenant) gets its own graph, and every person gets a private graph next to it, all on one FalkorDB instance. Private notes stay private until someone deliberately promotes them to the team.

I chose separate graphs over a `WHERE tenant = ...` property for three reasons:
- **Isolation by construction.** A forgotten filter can't leak another team's memory.
- **Better vector search.** It doesn't combine well with property filters, and inside a tenant's own graph every vector hit already belongs to that tenant.
- **Writes don't queue behind other tenants.** That's the 18% throughput gain in the 100-agent row above.

## Steal these

Design rules I'd use again on any agent-memory project:

1. **Never let the model write the query.** Agents get 22 typed MCP tools, and each one runs a fixed, parameterised Cypher query. No injection surface, and every query is indexed.
2. **Put the check and the write in one query.** FalkorDB's per-graph write ordering is free concurrency control.
3. **Memory must fail open.** If the server or FalkorDB is down, hooks exit silently and the agent keeps working. The dashboard says *"Can't reach FalkorDB"* and recovers by itself.
4. **Redact before you remember.** Agents see secrets all day. API keys, tokens, JWTs and `password=` values are stripped before anything is stored.

## What bit me

The honest part, because a post that only shows the happy path doesn't help anyone.

- **My "known fix" lied at first.** For a Postgres connection error, it suggested an unrelated note about a flaky test, because both mentioned `pytest`. Worse, my error parser had grabbed pytest's summary line (`1 failed, 41 errors in 3.2s`) as the "error". The fix: extract the real root-cause line and compare memories to *that*, not to the command. There's now a test asserting that the very first failure of something gets **no** hint.
- **Label propagation flip-flopped on tiny graphs.** Running community detection alone on a small, star-shaped entity graph split obvious groups apart. Now topics come from connected components first (`algo.WCC`), and label propagation only splits the big ones.
- **The vector score is a distance.** FalkorDB's cosine score is *lower-is-closer*, so I convert it to similarity before ranking. I learned that from a near-identical match scoring 0.006.
- **`uv run pytest -q` and `pytest -q` are the same step.** Until I normalised commands, the same fix showed up as two "different" procedures and never got reinforced.
- **My server died with the database.** If FalkorDB wasn't up at boot, the server crashed. Now the connection is lazy, FalkorDB outages return a clean 503 in about three seconds, and everything recovers when FalkorDB comes back. On Windows, connecting to `localhost` instead of `127.0.0.1` alone added seconds to every failure.

## Does it actually help? I measured, and the first answer was no

I ran real Claude Code (Opus 5.5, headless) on a small payments repo: *"add `apply_discount`, follow the team's conventions, make the suite pass."* There were two runs with Hivemind and two without, and hidden checks verified correctness.

**Round one: every rule was also written in the repo.**

| | Turns | Cost per run | Correct |
|---|---|---|---|
| Without Hivemind | 5 | $0.33 | 2/2 |
| With Hivemind | 5.5 | $0.33 | 2/2 |

No difference. Claude read the error message and the conventions doc and worked everything out itself. My first reaction was disappointment; my second was that this is exactly right. **Memory isn't for what's already written down.**

**Round two: the rule lived only in a teammate's earlier session.** I removed the conventions doc. The finance team's decision (discounts are capped at 50% and round *down*) existed only in what an earlier agent had recorded.

| | Turns | Cost per run | Correct |
|---|---|---|---|
| Without Hivemind | 4.5 | $0.22 | **0/2** |
| With Hivemind | 7 | $0.27 | **2/2** |

Without memory, both runs did the sensible thing from the code (half-up rounding with the existing helper) and got it wrong. With Hivemind, both applied the team's rules. One even told me the rules came from the team's shared notes and asked me to confirm them.

It wasn't free: about 2.5 more turns and 5 cents more per run. Two runs per side is a small sample, so read the correctness gap as the signal and the cost as a real trade-off. I'd still pay five cents not to ship the wrong refund rule.

## Try it

```bash
docker compose up -d
# open http://localhost:8765 and press "Play the demo"
```

You'll watch three agents (Claude Code, Cursor and Codex) share one memory:
- a procedure gets learned automatically
- a collision gets avoided
- the CI agent gets the fix at the moment of failure
- a task is handed off with its context attached
- three agents race for one task, and exactly one wins

To connect your own agents:

```bash
uv run hivemind install claude-code --dir path/to/your/repo --workspace my-team --user me
```

## TL;DR

Agent memory isn't a longer prompt; it's a graph with time in it. It records what happened, what's true and since when, how to do things and whether that worked, and who's doing what right now. FalkorDB gave me vectors, full-text search, multi-hop traversal, graph algorithms, per-tenant graphs and race-free writes in one place, so the interesting work was deciding what the team should remember.

And when I measured it honestly, a strong model didn't need help with what's in the code. It needed help with what's in the team's heads.

**What's the one thing you'd want your agents to stop rediscovering?**

---

*Built for Graph Hacks by WeMakeDevs × FalkorDB. Hivemind is open source (MIT): [github.com/Lecrupus/hivemind](https://github.com/Lecrupus/hivemind). I built it with Claude Code as a pair programmer; the README has the full disclosure.*
