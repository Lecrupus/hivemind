# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences share one dashboard, demo first:

- **Evaluators seeing Hivemind for the first time** (hackathon judges, curious engineers). They open the dashboard, press **Play the demo**, and need to understand within about 60 seconds that three AI agents are sharing one memory: a procedure learned automatically, a collision avoided, a known fix served at the moment of failure, a handoff, a superseded fact, an atomic claim race, promotion and consolidation.
- **Engineering leads running several coding agents** (Claude Code, Cursor, Codex) on one codebase. They check who is live and editing what, which tasks are claimed or handed off, what the team has learned, and why a memory exists.

## Product Purpose

Hivemind is a shared, time-aware memory and coordination layer for teams of AI coding agents, stored as a graph in FalkorDB. Agents connect over MCP and Claude Code hooks. The dashboard makes that shared memory visible: agents, their work, what they learned, the topics it touches, how knowledge changed over time, and the provenance of any memory. Success: an evaluator can retell the demo story afterwards, and a lead can answer "who is doing what, and why do we believe this?" without leaving the page.

## Positioning

Memory that agents write *by working* (procedures mined from fail → fix → success, errors answered with the team's verified fix), held as a bi-temporal graph: facts are superseded, never overwritten, so any moment in the past can be viewed, and every memory can explain where it came from.

## Operating Context

- Single-page dashboard served by the Hivemind FastAPI server (`hivemind serve`, default http://127.0.0.1:8765), usually alongside FalkorDB in Docker.
- Live updates arrive over SSE from FalkorDB pub/sub; the scripted demo (`/api/demo/play`) narrates itself with captions.
- Workspaces: one graph per team/tenant, selectable in the dashboard.
- Views today: relationship map (agents → work → knowledge → topics), task board (open / in progress / handed off / done), raw graph explorer (force-graph), time-travel slider, inspector (details + provenance, recall search, activity feed, benchmarks).

## Capabilities and Constraints

- **Stack is fixed:** vanilla JS, no build step: `src/hivemind/web/index.html`, `app.js`, `styles.css`, plus `force-graph` from a CDN. The README advertises "vanilla JS, no build step".
- All data comes from the existing REST endpoints (`/api/graph`, `/api/team`, `/api/stats`, `/api/node`, `/api/why`, `/api/recall`, `/api/timeline`, `/api/feed`, `/api/time-range`, `/api/bench`, `/api/workspaces`, `/api/consolidate`, `/api/demo/*`, `/api/events`). The redesign must not change backend behaviour.
- Read endpoints are unauthenticated; the "Play the demo" action only touches the `demo` workspace.
- Terminology: Agent, Session, Episode, Fact, Procedure, Task, Handoff, Entity, Topic; "supersede", "promote", "consolidate", "recall", "why", "known fix served", "time travel".

## Brand Commitments

- The Hivemind logo mark (three nodes joined in a triangle) stays; its colour may change.
- Light mode is the default theme; dark mode is the alternative.
- Agent client identities are recognisable: Claude Code, Cursor, Codex.

## Evidence on Hand

- Benchmarks in `src/hivemind/web/bench/*.json` (concurrency: ~1,300 ops/s at 100 agents, 20/20 single-winner claim races; Claude Code A/B: 0/2 → 2/2 correct when knowledge lived only in team memory, ~23% higher cost; no difference when knowledge was also in the repo).
- Screenshots in `docs/img/` (relationship map, provenance, task board) are of the previous UI and will be outdated by a redesign.
- No customers, testimonials or pricing exist; none may be invented.

## Product Principles

1. **Show the mechanism, not a claim.** Every panel should make a memory operation visible: learned, served, superseded, claimed, handed off.
2. **Honest about uncertainty.** "Not in the graph" beats a guess; ranking and provenance are always explainable.
3. **Time is a first-class dimension.** Past belief is kept and viewable, never silently replaced.
4. **The demo tells a story; the tool stays usable.** Narration and highlights serve first-time viewers without getting in a working lead's way.
