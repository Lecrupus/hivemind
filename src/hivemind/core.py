"""Hivemind core: every memory and coordination operation.

The MCP server, the Claude Code hooks, the REST API and the dashboard are all
thin layers over the `Hivemind` class. Each call takes an `Actor` (which
workspace, which human, which agent, which session) so one process can serve
many agents and tenants at once."""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

from . import queries as Q
from .config import Settings, slug
from .db import GraphDB, parse_graph_name, private_graph_name, shared_graph_name
from .embeddings import make_embedder
from .events import EventBus
from .text import (ago, clip, command_key, entity_id, extract_entities, module_of, new_id, normalize_command, now_ms,
                   redact)

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# id prefix -> label. Labels can't be query parameters, so templates get one
# of these whitelisted values substituted in.
_PREFIX_LABELS = [("f_", "Fact"), ("p_", "Procedure"), ("ep_", "Episode"), ("t_", "Task"),
                  ("h_", "Handoff"), ("s_", "Session"), ("adhoc_", "Session"), ("topic_", "Topic")]


def label_for(node_id: str) -> str:
    for prefix, label in _PREFIX_LABELS:
        if node_id.startswith(prefix):
            return label
    if "@" in node_id:
        return "Agent"
    return "Entity"


def _tpl(query: str, label: str) -> str:
    assert label in Q.LABELS_WITH_ID, label
    return query.replace("__LABEL__", label)


def _fts_query(text: str) -> str | None:
    """RediSearch query: any of the meaningful words. Plain terms so English stemming
    applies ("tests" matches "test")."""
    stop = {"the", "and", "for", "with", "how", "what", "does", "this", "that", "from", "are", "was", "our",
            "can", "should", "when", "where", "which", "who", "why", "you", "use", "into", "have", "has", "run"}
    words = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", text.lower()) if w not in stop][:8]
    return "|".join(words) or None


def _norm_steps(steps: list[str]) -> list[str]:
    return [normalize_command(s) for s in steps if s and s.strip()]


def success_rate(s: int, f: int) -> float:
    """Laplace-smoothed success rate: a procedure that worked 1/1 isn't 'perfect'."""
    return (s + 1.0) / (s + f + 2.0)


@dataclass
class Actor:
    workspace: str
    user: str
    agent_id: str
    client: str = "custom"
    role: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    branch: str | None = None

    @classmethod
    def from_settings(cls, s: Settings, **kw) -> "Actor":
        base = cls(workspace=s.workspace, user=s.user, agent_id=s.resolved_agent_id, client=s.client, role=s.role)
        return replace(base, **{k: v for k, v in kw.items() if v is not None})


class Hivemind:
    # Cosine-similarity thresholds, calibrated for bge-small-en-v1.5.
    DUPLICATE_SIM = 0.93  # same fact said twice -> reinforce instead of duplicating
    CONFLICT_SIM = 0.82  # close enough that it may contradict -> surface to the agent
    PROCEDURE_MATCH_SIM = 0.86
    RELEVANT_SIM = 0.70
    MIN_SEMANTIC_ONLY = 0.68
    MAX_TOPIC_SIZE = 25

    def __init__(self, settings: Settings | None = None, embedder=None, db: GraphDB | None = None):
        self.settings = settings or Settings.from_env()
        self.embedder = embedder or make_embedder(self.settings.embedder, self.settings.model_cache)
        self.db = db or GraphDB(self.settings.falkordb_url, self.embedder.dim)
        self.events = EventBus(self.db.redis)
        self._session_seen: dict[tuple[str, str], int] = {}
        self._graph_cache: tuple[float, set[str]] = (0.0, set())
        self._lock = threading.Lock()

    # ------------------------------------------------------------ plumbing

    def shared(self, actor: Actor) -> str:
        return shared_graph_name(actor.workspace)

    def private(self, actor: Actor) -> str:
        return private_graph_name(actor.workspace, actor.user)

    def _graph(self, actor: Actor, private: bool) -> str:
        return self.private(actor) if private else self.shared(actor)

    def graph_exists(self, name: str) -> bool:
        ts, names = self._graph_cache
        if time.time() - ts > 5 or name not in names:
            names = set(self.db.list_graphs())
            self._graph_cache = (time.time(), names)
        return name in names

    def _readable_graphs(self, actor: Actor, include_private: bool = True) -> list[tuple[str, str]]:
        out = [(self.shared(actor), "team")]
        if include_private and self.graph_exists(self.private(actor)):
            out.append((self.private(actor), "private"))
        return out

    def embed(self, text: str) -> list[float]:
        return self.embedder.embed([text])[0]

    def _publish(self, actor: Actor, type_: str, **data) -> None:
        self.events.publish(actor.workspace, type_, agent=actor.agent_id, user=actor.user, **data)

    def _locate(self, actor: Actor, node_id: str) -> tuple[str, str] | None:
        """Find which of the actor's graphs holds a node: (graph, label)."""
        label = label_for(node_id)
        for graph, _ in self._readable_graphs(actor):
            if self.db.ro_query(graph, _tpl(Q.EXISTS_NODE, label), {"id": node_id}):
                return graph, label
        return None

    def _link_entities(self, graph: str, entities: list[dict]) -> None:
        """Entities mentioned together are related; a file is related to its module (directory)."""
        ids = sorted({e["id"] for e in entities})[:8]
        pairs = [[a, b] for i, a in enumerate(ids) for b in ids[i + 1:]]
        modules = []
        for e in entities:
            mod = module_of(e["name"]) if e["type"] == "file" else None
            if mod:
                modules.append({"id": entity_id(mod), "name": mod, "type": "module"})
                pairs.append(sorted([e["id"], entity_id(mod)]))
        if modules:
            self.db.query(graph, Q.MERGE_ENTITIES, {"entities": modules, "now": now_ms()})
        if pairs:
            self.db.query(graph, Q.LINK_ENTITIES, {"pairs": pairs, "now": now_ms()})

    # ------------------------------------------------------------ sessions

    def _upsert_session(self, graph: str, actor: Actor) -> None:
        self.db.query(graph, Q.UPSERT_SESSION, {
            "user": actor.user, "agent_id": actor.agent_id, "client": actor.client, "role": actor.role,
            "session_id": actor.session_id, "cwd": actor.cwd, "branch": actor.branch, "now": now_ms(),
        })
        self._session_seen[(graph, actor.session_id)] = now_ms()

    def start_session(self, actor: Actor, session_id: str | None = None) -> str:
        actor.session_id = session_id or actor.session_id or new_id("s")
        self._upsert_session(self.shared(actor), actor)
        self._publish(actor, "session.started", session=actor.session_id, client=actor.client)
        return actor.session_id

    def ensure_session(self, actor: Actor, graph: str | None = None) -> str:
        """Resolve the actor's session (explicit, latest active, or a daily ad-hoc one)
        and make sure it exists in `graph`, refreshing presence at most once a minute."""
        graph = graph or self.shared(actor)
        if not actor.session_id:
            rows = self.db.ro_query(self.shared(actor), Q.LATEST_ACTIVE_SESSION,
                                    {"agent_id": actor.agent_id, "since": now_ms() - 2 * HOUR})
            actor.session_id = rows[0]["id"] if rows else f"adhoc_{slug(actor.agent_id)}_{time.strftime('%Y%m%d')}"
        last = self._session_seen.get((graph, actor.session_id), 0)
        if now_ms() - last > MINUTE:
            self._upsert_session(graph, actor)
        return actor.session_id

    def end_session(self, actor: Actor, reason: str = "ended") -> None:
        if not actor.session_id:
            return
        for graph, _ in self._readable_graphs(actor):
            self.db.query(graph, Q.END_SESSION, {"session_id": actor.session_id, "now": now_ms(), "reason": reason})
        self._publish(actor, "session.ended", session=actor.session_id)

    # ------------------------------------------------------------ episodic memory

    def remember(self, actor: Actor, text: str, kind: str = "note", about: list[str] | None = None,
                 importance: float = 0.5, private: bool = False) -> dict:
        """Record something that happened (an episode) in the actor's session."""
        text = redact(clip(text, 4000))
        graph = self._graph(actor, private)
        sid = self.ensure_session(actor, graph)
        ents = extract_entities(text, about)
        eid = new_id("ep")
        self.db.query(graph, Q.ADD_EPISODE, {
            "session_id": sid, "id": eid, "now": now_ms(), "kind": kind, "text": text,
            "importance": importance, "agent_id": actor.agent_id, "embedding": self.embed(text),
            "entities": ents,
        })
        self._link_entities(graph, ents)
        self._publish(actor, "episode.added", id=eid, kind=kind, text=clip(text, 200), private=private,
                      session=sid)
        return {"id": eid, "kind": kind, "entities": [e["name"] for e in ents], "scope": "private" if private else "team"}

    HISTORY_KINDS = ["prompt", "response", "note", "decision", "error", "action", "handoff", "outcome"]

    def history(self, actor: Actor, query: str | None = None, limit: int = 20, session_id: str | None = None,
                agent_id: str | None = None, mine_only: bool = False) -> list[dict]:
        """Conversation history across sessions: chronological, or semantic if `query` is given."""
        graph = self.shared(actor)
        if query:
            rows = self.db.ro_query(graph, Q.VECTOR_EPISODES, {
                "k": limit * 2, "embedding": self.embed(query), "as_of": now_ms(),
                "exclude_kinds": ["learning", "edit", "assist"]})
            rows = [r for r in rows if r["sim"] >= 0.55][:limit]
        else:
            rows = self.db.ro_query(graph, Q.HISTORY, {
                "session_id": session_id, "agent_id": agent_id, "user": actor.user if mine_only else None,
                "kinds": self.HISTORY_KINDS, "limit": limit})
        for r in rows:
            r["when"] = ago(r.get("ts"))
        return rows

    # ------------------------------------------------------------ semantic memory

    def _similar_facts(self, graph: str, embedding: list[float], k: int = 8) -> list[dict]:
        return self.db.ro_query(graph, Q.VECTOR_FACTS, {"k": k, "embedding": embedding, "as_of": now_ms()})

    def learn(self, actor: Actor, statement: str, kind: str = "fact", key: str | None = None,
              about: list[str] | None = None, confidence: float = 0.8, private: bool = False,
              episode_id: str | None = None, promoted_from: str | None = None) -> dict:
        """Store a durable fact. Deduplicates, supersedes by key, and surfaces likely contradictions."""
        statement = redact(clip(statement, 1000)).strip()
        if not statement:
            raise ValueError("statement is empty")
        graph = self._graph(actor, private)
        self.ensure_session(actor, graph)
        emb = self.embed(statement)
        key = slug(key) if key else None
        to_supersede: list[dict] = []
        conflicts: list[dict] = []

        if key:
            to_supersede = self.db.ro_query(graph, Q.ACTIVE_FACT_BY_KEY, {"key": key})
            same = [f for f in to_supersede if f["statement"].strip().lower() == statement.lower()]
            if same:
                return self._reinforce(actor, graph, same[0])
        else:
            for f in self._similar_facts(graph, emb):
                if f["sim"] >= self.DUPLICATE_SIM:
                    return self._reinforce(actor, graph, f)
                if f["sim"] >= self.CONFLICT_SIM:
                    conflicts.append({"id": f["id"], "statement": f["statement"], "similarity": round(f["sim"], 3)})

        if not episode_id:  # every fact has provenance, even when stated directly
            episode_id = self.remember(actor, f"Learned: {statement}", kind="learning", about=about,
                                       importance=0.3, private=private)["id"]
        fid = new_id("f")
        ents = extract_entities(statement, about)
        now = now_ms()
        self.db.query(graph, Q.ADD_FACT, {
            "agent_id": actor.agent_id, "episode_id": episode_id, "id": fid, "statement": statement,
            "kind": kind, "key": key, "confidence": float(confidence), "valid_from": now, "now": now,
            "scope": "private" if private else "team", "promoted_from": promoted_from,
            "embedding": emb, "entities": ents,
        })
        self._link_entities(graph, ents)
        superseded = []
        for old in to_supersede:
            self.db.query(graph, Q.SUPERSEDE_FACT, {"old_id": old["id"], "new_id": fid, "now": now,
                                                     "reason": f"updated value for '{key}'", "agent_id": actor.agent_id})
            superseded.append({"id": old["id"], "statement": old["statement"]})
        self._publish(actor, "fact.learned", id=fid, text=clip(statement, 200), kind=kind, private=private,
                      superseded=[s["id"] for s in superseded])
        out: dict[str, Any] = {"status": "created", "id": fid, "scope": "private" if private else "team",
                               "entities": [e["name"] for e in ents]}
        if superseded:
            out["superseded"] = superseded
        if conflicts:
            out["possible_conflicts"] = conflicts
            out["hint"] = "If this fact replaces one of possible_conflicts, call supersede(old_id, new_fact_id)."
        return out

    def _reinforce(self, actor: Actor, graph: str, fact: dict) -> dict:
        rows = self.db.query(graph, Q.REINFORCE_FACT, {"id": fact["id"], "agent_id": actor.agent_id, "now": now_ms()})
        conf = rows[0]["confidence"] if rows else fact.get("confidence")
        self._publish(actor, "fact.reinforced", id=fact["id"], text=clip(fact["statement"], 200))
        return {"status": "reinforced", "id": fact["id"], "statement": fact["statement"],
                "confidence": round(conf or 0, 2),
                "note": "An equivalent fact already existed; it was reinforced instead of duplicated."}

    def supersede(self, actor: Actor, old_id: str, new_statement: str | None = None, new_id_: str | None = None,
                  reason: str = "") -> dict:
        """Mark a fact as no longer true, linked to what replaced it. History is kept."""
        loc = self._locate(actor, old_id)
        if not loc or loc[1] != "Fact":
            return {"error": f"No fact with id {old_id}"}
        graph = loc[0]
        old = self.db.ro_query(graph, Q.GET_FACT, {"id": old_id})[0]
        if new_id_ is None:
            if not new_statement:
                return {"error": "Give new_statement or new_id"}
            res = self.learn(actor, new_statement, kind=old.get("kind") or "fact", about=old.get("entities"),
                             private=graph != self.shared(actor))
            new_id_ = res["id"]
            if new_id_ == old_id:
                return {"error": "The new statement is equivalent to the old fact; nothing to supersede."}
        self.db.query(graph, Q.SUPERSEDE_FACT, {"old_id": old_id, "new_id": new_id_, "now": now_ms(),
                                                 "reason": reason or "superseded", "agent_id": actor.agent_id})
        self._publish(actor, "fact.superseded", id=old_id, new_id=new_id_, text=clip(old["statement"], 200))
        return {"status": "superseded", "old": {"id": old_id, "statement": old["statement"]}, "new_id": new_id_}

    def forget(self, actor: Actor, node_id: str, reason: str = "", hard: bool = False) -> dict:
        """Retract a memory (kept for audit, never recalled) or hard-delete it and what derived only from it."""
        loc = self._locate(actor, node_id)
        if not loc or loc[1] not in {"Fact", "Procedure", "Episode"}:
            return {"error": f"No fact, procedure or episode with id {node_id}"}
        graph, label = loc
        if hard:
            rows = self.db.query(graph, _tpl(Q.HARD_DELETE, label), {"id": node_id})
            derived = rows[0]["derived_count"] if rows else 0
            self._publish(actor, "memory.deleted", id=node_id, derived=derived)
            return {"status": "deleted", "id": node_id, "derived_deleted": derived}
        rows = self.db.query(graph, _tpl(Q.RETRACT, label), {"id": node_id, "now": now_ms(), "reason": reason,
                                                             "agent_id": actor.agent_id})
        self._publish(actor, "memory.retracted", id=node_id)
        return {"status": "retracted", "id": node_id, "text": rows[0]["text"] if rows else None}

    def promote(self, actor: Actor, fact_id: str) -> dict:
        """Share a private fact with the team (the private copy is marked promoted)."""
        priv = self.private(actor)
        if not self.graph_exists(priv):
            return {"error": "No private memory yet"}
        rows = self.db.ro_query(priv, Q.GET_FACT, {"id": fact_id})
        if not rows:
            return {"error": f"No private fact with id {fact_id}"}
        f = rows[0]
        res = self.learn(actor, f["statement"], kind=f["kind"] or "fact", key=f.get("key"), about=f.get("entities"),
                         confidence=f["confidence"] or 0.8, promoted_from=f"{actor.user}:{fact_id}")
        self.db.query(priv, Q.MARK_PROMOTED, {"id": fact_id, "new_id": res["id"], "now": now_ms()})
        self._publish(actor, "fact.promoted", id=res["id"], private_id=fact_id, text=clip(f["statement"], 200))
        return {"status": "promoted", "team_fact": res}

    # ------------------------------------------------------------ recall

    def recall(self, actor: Actor, query: str, k: int = 8, as_of: int | None = None, include_private: bool = True,
               types: tuple[str, ...] = ("fact", "procedure", "episode"), bump: bool = True) -> dict:
        """Hybrid retrieval: vector + full-text + graph expansion, ranked and explained."""
        now = now_ms()
        as_of = int(as_of or now)
        emb = self.embed(query)
        q_ents = [e["id"] for e in extract_entities(query)]
        fts = _fts_query(query)
        results: dict[str, dict] = {}

        def slot(item: dict, type_: str, scope: str) -> dict:
            r = results.get(item["id"])
            if r is None:
                r = results[item["id"]] = {"type": type_, "scope": scope, "sim": 0.0, "fts": 0.0, "hops": None,
                                           "data": item}
            return r

        for graph, scope in self._readable_graphs(actor, include_private):
            if "fact" in types:
                for f in self.db.ro_query(graph, Q.VECTOR_FACTS, {"k": k * 3, "embedding": emb, "as_of": as_of}):
                    slot(f, "fact", scope)["sim"] = f["sim"]
                if fts:
                    rows = self._safe_fts(graph, Q.FULLTEXT_FACTS, fts, k * 2, as_of)
                    top = max((r["fts"] for r in rows), default=1.0) or 1.0
                    for f in rows:
                        slot(f, "fact", scope)["fts"] = f["fts"] / top
                if q_ents:
                    for f in self.db.ro_query(graph, Q.ENTITY_FACTS, {"entity_ids": q_ents, "k": k * 2, "as_of": as_of}):
                        r = slot(f, "fact", scope)
                        r["hops"] = f["hops"]
                        r["via"] = f["via"]
            if "procedure" in types:
                for p in self.db.ro_query(graph, Q.VECTOR_PROCEDURES, {"k": k, "embedding": emb, "as_of": as_of}):
                    slot(p, "procedure", scope)["sim"] = p["sim"]
                if q_ents:
                    for p in self.db.ro_query(graph, Q.PROCEDURES_FOR_ENTITY, {"entity_ids": q_ents}):
                        slot(p, "procedure", scope)["hops"] = 0
            if "episode" in types:
                for e in self.db.ro_query(graph, Q.VECTOR_EPISODES, {
                        "k": k * 2, "embedding": emb, "as_of": as_of, "exclude_kinds": ["learning", "edit", "assist"]}):
                    slot(e, "episode", scope)["sim"] = e["sim"]

        ranked = []
        for rid, r in results.items():
            d = r["data"]
            entity = 1.0 if r["hops"] == 0 else 0.6 if r["hops"] == 1 else 0.0
            # bge-small puts unrelated English around 0.55-0.65 cosine, so a purely
            # semantic match must clear a higher bar than one backed by keywords or the graph.
            if r["sim"] < self.MIN_SEMANTIC_ONLY and r["fts"] == 0 and entity == 0:
                continue
            if r["type"] == "fact":
                score = 0.6 * r["sim"] + 0.15 * r["fts"] + 0.15 * entity + 0.05 * (d.get("confidence") or 0) \
                        + 0.05 * min(1.0, d.get("importance") or 0)
            elif r["type"] == "procedure":
                rate = success_rate(d.get("success_count") or 0, d.get("fail_count") or 0)
                score = 0.65 * r["sim"] + 0.15 * entity + 0.2 * rate
            else:
                age_days = max(0.0, (now - (d.get("ts") or now)) / DAY)
                score = 0.85 * (0.75 * r["sim"] + 0.25 * math.exp(-age_days / 7))
            ranked.append({
                "type": r["type"], "id": rid, "scope": r["scope"], "score": round(score, 3),
                "text": d.get("statement") or d.get("goal") or d.get("text"),
                "why_ranked": {"semantic": round(r["sim"], 3), "keyword": round(r["fts"], 3),
                               "graph_hops": r["hops"], "via": r.get("via")},
                "data": d,
            })
        ranked.sort(key=lambda x: x["score"], reverse=True)
        top = ranked[:k]
        self._attach_provenance(actor, top)
        if bump:
            self._bump(actor, top)
        items = [self._present(r) for r in top]
        return {"query": query, "as_of": as_of, "results": items, "summary": self._summarize(items)}

    def _safe_fts(self, graph: str, query: str, fts: str, k: int, as_of: int) -> list[dict]:
        try:
            return self.db.ro_query(graph, query, {"q": fts, "k": k, "as_of": as_of})
        except Exception:  # odd input the full-text parser rejects: skip that signal
            return []

    def _attach_provenance(self, actor: Actor, items: list[dict]) -> None:
        for graph, scope in self._readable_graphs(actor):
            for label, type_ in (("Fact", "fact"), ("Procedure", "procedure")):
                ids = [i["id"] for i in items if i["type"] == type_ and i["scope"] == scope]
                if not ids:
                    continue
                prov = {p["id"]: p for p in self.db.ro_query(graph, _tpl(Q.PROVENANCE, label), {"ids": ids})}
                for i in items:
                    if i["id"] in prov:
                        i["provenance"] = prov[i["id"]]

    def _bump(self, actor: Actor, items: list[dict]) -> None:
        for graph, scope in self._readable_graphs(actor):
            for label, type_ in (("Fact", "fact"), ("Procedure", "procedure")):
                ids = [i["id"] for i in items if i["type"] == type_ and i["scope"] == scope]
                if ids:
                    self.db.query(graph, _tpl(Q.BUMP_USES, label), {"ids": ids, "now": now_ms()})

    def _present(self, r: dict) -> dict:
        d = r["data"]
        out = {k: r[k] for k in ("type", "id", "scope", "score", "text", "why_ranked")}
        if r["type"] == "fact":
            out.update(kind=d.get("kind"), confidence=d.get("confidence"), learned=ago(d.get("recorded_at")),
                       status=d.get("status"), valid_from=d.get("valid_from"), valid_to=d.get("valid_to"))
        elif r["type"] == "procedure":
            out.update(steps=d.get("steps"), success_count=d.get("success_count"), fail_count=d.get("fail_count"),
                       success_rate=round(success_rate(d.get("success_count") or 0, d.get("fail_count") or 0), 2),
                       auto_learned=bool(d.get("auto")), last_used=ago(d.get("last_used")))
        else:
            out.update(kind=d.get("kind"), agent=d.get("agent_id"), when=ago(d.get("ts")))
        p = r.get("provenance")
        if p:
            out["provenance"] = {"learned_by": p.get("agents"), "about": p.get("entities"),
                                 "source": clip(p.get("source_text") or "", 200) or None,
                                 "source_session": p.get("source_session")}
        return out

    @staticmethod
    def _summarize(items: list[dict]) -> str:
        if not items:
            return "Nothing in Hivemind memory matches this. (Not in the graph: don't assume.)"
        lines = []
        for i in items:
            who = ", ".join((i.get("provenance") or {}).get("learned_by") or []) or i.get("agent") or "?"
            if i["type"] == "fact":
                lines.append(f"[fact {i['id']} | {i['scope']} | conf {i.get('confidence') or 0:.2f} | "
                             f"{who}, {i.get('learned')}] {i['text']}")
            elif i["type"] == "procedure":
                steps = " -> ".join(i.get("steps") or [])
                lines.append(f"[procedure {i['id']} | worked {i.get('success_count')}x, failed {i.get('fail_count')}x"
                             f" | {who}] {i['text']}: {steps}")
            else:
                lines.append(f"[{i.get('kind')} {i['id']} | {who}, {i.get('when')}] {clip(i['text'] or '', 240)}")
        return "\n".join(lines)

    # ------------------------------------------------------------ procedural memory

    def record_procedure(self, actor: Actor, goal: str, steps: list[str], outcome: str = "success",
                         about: list[str] | None = None, private: bool = False, auto: bool = False,
                         episode_ids: list[str] | None = None) -> dict:
        """Store how to do something. Same steps again -> reinforced; different steps -> a new revision."""
        goal = redact(clip(goal, 300)).strip()
        steps = [redact(clip(s, 400)) for s in steps if s and s.strip()][:15]
        if not goal or not steps:
            raise ValueError("goal and steps are required")
        ok = outcome.lower() in {"success", "succeeded", "ok", "worked", "true", "pass", "passed"}
        graph = self._graph(actor, private)
        self.ensure_session(actor, graph)
        emb = self.embed(goal)
        near = [p for p in self.db.ro_query(graph, Q.VECTOR_PROCEDURES, {"k": 5, "embedding": emb, "as_of": now_ms()})
                if p["sim"] >= self.PROCEDURE_MATCH_SIM]
        for p in near:
            if _norm_steps(p["steps"] or []) == _norm_steps(steps):
                counts = self.report_outcome(actor, p["id"], ok, notes="same steps recorded again", _graph=graph)
                return {"status": "reinforced", "id": p["id"], "goal": p["goal"], **counts}
        pid = new_id("p")
        step_cmds = [k for k in (command_key(s) for s in steps) if k]
        ents = extract_entities(goal + "\n" + "\n".join(steps), list(about or []) + step_cmds)
        self.db.query(graph, Q.ADD_PROCEDURE, {
            "agent_id": actor.agent_id, "id": pid, "goal": goal, "steps": steps, "success": 1 if ok else 0,
            "fail": 0 if ok else 1, "now": now_ms(), "auto": auto, "embedding": emb, "entities": ents,
            "revises": near[0]["id"] if near else None,
        })
        if episode_ids:
            self.db.query(graph, _tpl(Q.LINK_SOURCES, "Procedure"), {"id": pid, "episode_ids": episode_ids})
        self._link_entities(graph, ents)
        self._publish(actor, "procedure.learned", id=pid, text=clip(goal, 200), steps=steps, auto=auto, ok=ok)
        out = {"status": "created", "id": pid, "goal": goal, "steps": steps, "outcome": "success" if ok else "failure"}
        if near:
            out["revises"] = near[0]["id"]
        return out

    def find_procedure(self, actor: Actor, goal: str, k: int = 3) -> list[dict]:
        emb = self.embed(goal)
        q_ents = [e["id"] for e in extract_entities(goal)]
        found: dict[str, dict] = {}
        for graph, scope in self._readable_graphs(actor):
            for p in self.db.ro_query(graph, Q.VECTOR_PROCEDURES, {"k": k * 3, "embedding": emb, "as_of": now_ms()}):
                found[p["id"]] = {**p, "scope": scope}
            if q_ents:
                for p in self.db.ro_query(graph, Q.PROCEDURES_FOR_ENTITY, {"entity_ids": q_ents}):
                    found.setdefault(p["id"], {**p, "scope": scope, "sim": 0.0})["entity_match"] = True
        ranked = []
        for p in found.values():
            sim = max(p.get("sim", 0.0), 0.75 if p.get("entity_match") else 0.0)
            if sim < 0.6:
                continue
            rate = success_rate(p["success_count"] or 0, p["fail_count"] or 0)
            ranked.append({"id": p["id"], "goal": p["goal"], "steps": p["steps"], "scope": p["scope"],
                           "success_count": p["success_count"], "fail_count": p["fail_count"],
                           "success_rate": round(rate, 2), "auto_learned": bool(p.get("auto")),
                           "created_by": p.get("created_by"), "last_used": ago(p.get("last_used")),
                           "similarity": round(p.get("sim", 0.0), 3), "entity_match": bool(p.get("entity_match")),
                           "score": round(sim * (0.4 + 0.6 * rate), 3)})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked[:k]

    def report_outcome(self, actor: Actor, procedure_id: str, success: bool, notes: str = "",
                       _graph: str | None = None) -> dict:
        graph = _graph or (self._locate(actor, procedure_id) or (None,))[0]
        if not graph:
            return {"error": f"No procedure with id {procedure_id}"}
        sid = self.ensure_session(actor, graph)
        rows = self.db.query(graph, Q.PROCEDURE_OUTCOME, {
            "id": procedure_id, "success": 1 if success else 0, "fail": 0 if success else 1, "now": now_ms(),
            "session_id": sid, "ok": bool(success), "notes": clip(notes, 300)})
        self._publish(actor, "procedure.outcome", id=procedure_id, ok=bool(success))
        return rows[0] if rows else {"error": f"No procedure with id {procedure_id}"}

    # ------------------------------------------------------------ coordination

    def create_task(self, actor: Actor, title: str, description: str = "", about: list[str] | None = None,
                    claim: bool = False) -> dict:
        graph = self.shared(actor)
        self.ensure_session(actor, graph)
        tid = new_id("t")
        ents = extract_entities(title + "\n" + description, about)
        self.db.query(graph, Q.CREATE_TASK, {"agent_id": actor.agent_id, "id": tid, "title": clip(title, 200),
                                              "description": clip(description, 2000), "now": now_ms(), "entities": ents})
        self._publish(actor, "task.created", id=tid, text=clip(title, 200))
        out = {"status": "created", "id": tid, "title": title}
        if claim:
            out["claim"] = self.claim_task(actor, tid)
        return out

    def claim_task(self, actor: Actor, task_id: str, stale_after_min: int = 30) -> dict:
        """Atomically claim a task. Of many agents racing, exactly one wins."""
        graph = self.shared(actor)
        self.ensure_session(actor, graph)
        now = now_ms()
        rows = self.db.query(graph, Q.CLAIM_TASK, {"task_id": task_id, "agent_id": actor.agent_id, "now": now,
                                                    "stale_before": now - stale_after_min * MINUTE})
        if rows:
            self._publish(actor, "task.claimed", id=task_id, text=rows[0]["title"])
            return {"claimed": True, "task_id": task_id, "title": rows[0]["title"]}
        info = self.db.ro_query(graph, Q.TASK_INFO, {"task_id": task_id})
        if not info:
            return {"claimed": False, "error": f"No task with id {task_id}"}
        t = info[0]
        return {"claimed": False, "task_id": task_id, "status": t["status"], "held_by": t["claimed_by"],
                "since": ago(t["heartbeat"])}

    def complete_task(self, actor: Actor, task_id: str, summary: str = "") -> dict:
        graph = self.shared(actor)
        rows = self.db.query(graph, Q.COMPLETE_TASK, {"task_id": task_id, "now": now_ms(), "agent_id": actor.agent_id,
                                                       "summary": clip(summary, 1000)})
        if not rows:
            return {"error": f"No task with id {task_id}"}
        self.remember(actor, f"Completed task '{rows[0]['title']}': {summary}", kind="outcome")
        self._publish(actor, "task.completed", id=task_id, text=rows[0]["title"])
        return {"status": "done", "task_id": task_id}

    def list_tasks(self, actor: Actor, status: str | None = None, limit: int = 20) -> list[dict]:
        rows = self.db.ro_query(self.shared(actor), Q.FIND_TASKS, {"status": status, "limit": limit})
        for r in rows:
            r["updated"] = ago(r.get("updated_at"))
        return rows

    def handoff(self, actor: Actor, task_id: str, summary: str, next_steps: list[str] | None = None,
                to_agent: str | None = None, to_role: str | None = None, carry: list[str] | None = None) -> dict:
        """Pass a task to another agent (or role, or anyone) with the context it needs."""
        graph = self.shared(actor)
        self.ensure_session(actor, graph)
        hid = new_id("h")
        rows = self.db.query(graph, Q.CREATE_HANDOFF, {
            "task_id": task_id, "agent_id": actor.agent_id, "id": hid, "now": now_ms(),
            "summary": redact(clip(summary, 2000)), "next_steps": [clip(s, 300) for s in (next_steps or [])][:10],
            "to_role": to_role, "to_agent": to_agent})
        if not rows:
            return {"error": f"No task with id {task_id}"}
        carried = []
        for label in ("Fact", "Procedure", "Episode"):
            ids = [c for c in (carry or []) if label_for(c) == label]
            if ids:
                self.db.query(graph, _tpl(Q.CARRY, label), {"handoff_id": hid, "ids": ids})
                carried += ids
        ep = self.remember(actor, f"Handed off task {task_id} to {to_agent or to_role or 'anyone'}: {summary}",
                           kind="handoff")
        self._publish(actor, "handoff.created", id=hid, task=task_id, to=to_agent or to_role or "anyone",
                      text=clip(summary, 200), episode=ep["id"])
        return {"status": "handed_off", "handoff_id": hid, "task_id": task_id, "to": to_agent or to_role or "anyone",
                "carried": carried}

    def inbox(self, actor: Actor) -> list[dict]:
        rows = self.db.ro_query(self.shared(actor), Q.INBOX, {"agent_id": actor.agent_id, "role": actor.role})
        for r in rows:
            r["carried"] = [c for c in r["carried"] if c.get("id")]
            r["when"] = ago(r["ts"])
        return rows

    def accept_handoff(self, actor: Actor, handoff_id: str) -> dict:
        graph = self.shared(actor)
        self.ensure_session(actor, graph)
        rows = self.db.query(graph, Q.ACCEPT_HANDOFF, {"id": handoff_id, "agent_id": actor.agent_id, "now": now_ms()})
        if not rows:
            return {"error": f"No pending handoff {handoff_id}"}
        claim = self.claim_task(actor, rows[0]["task_id"])
        self._publish(actor, "handoff.accepted", id=handoff_id, task=rows[0]["task_id"])
        return {"status": "accepted", "handoff_id": handoff_id, "claim": claim}

    def touch_file(self, actor: Actor, path: str) -> None:
        graph = self.shared(actor)
        self.ensure_session(actor, graph)
        name = path.replace("\\", "/")
        if actor.cwd:
            root = actor.cwd.replace("\\", "/").rstrip("/") + "/"
            if name.lower().startswith(root.lower()):
                name = name[len(root):]
        self.db.query(graph, Q.TOUCH, {"session_id": actor.session_id, "entity_id": entity_id(name), "name": name,
                                        "now": now_ms()})
        self._publish(actor, "file.touched", file=name, session=actor.session_id)

    def file_conflicts(self, actor: Actor, path: str, window_min: int = 30) -> list[dict]:
        name = path.replace("\\", "/")
        if actor.cwd:
            root = actor.cwd.replace("\\", "/").rstrip("/") + "/"
            if name.lower().startswith(root.lower()):
                name = name[len(root):]
        rows = self.db.ro_query(self.shared(actor), Q.FILE_CONFLICTS, {
            "entity_id": entity_id(name), "since": now_ms() - window_min * MINUTE,
            "session_id": actor.session_id or ""})
        for r in rows:
            r["when"] = ago(r["at"])
            r["file"] = name
        return rows

    def team_status(self, actor: Actor, window_min: int = 30) -> list[dict]:
        now = now_ms()
        rows = self.db.ro_query(self.shared(actor), Q.TEAM_STATUS, {"since": now - window_min * MINUTE,
                                                                     "touch_since": now - window_min * MINUTE})
        for r in rows:
            r["last_seen_ago"] = ago(r["last_seen"])
            r["is_you"] = r["agent_id"] == actor.agent_id
        return rows

    # ------------------------------------------------------------ explainability

    def why(self, actor: Actor, node_id: str) -> dict:
        """Provenance: where a memory came from, who learned it, what it replaced, how it was used."""
        loc = self._locate(actor, node_id)
        if not loc:
            return {"error": f"Nothing with id {node_id} in your memory"}
        graph, label = loc
        rows = self.db.ro_query(graph, _tpl(Q.WHY, label), {"id": node_id})
        if not rows:
            return {"error": f"Nothing with id {node_id}"}
        row = rows[0]
        node = row["node"]
        nodes: dict[str, dict] = {}
        edges: set[tuple] = set()
        by_internal: dict[int, dict] = {}
        for group in ("origin", "replaced", "replaced_by", "learners", "about", "handoffs", "uses"):
            for p in row[group] or []:
                for n in p["nodes"]:
                    by_internal[n["_id"]] = n
                    nodes[n.get("id")] = {"id": n.get("id"), "label": n["labels"][0], "text": _node_text(n)}
                for e in p["edges"]:
                    edges.add((e["src"], e["type"], e["dst"]))
        edge_list = [{"src": by_internal.get(s, {}).get("id"), "type": t, "dst": by_internal.get(d, {}).get("id")}
                     for s, t, d in edges]
        story = _why_story(node, row, by_internal)
        return {"id": node_id, "label": label, "text": _node_text(node), "status": node.get("status"),
                "explanation": story, "graph": {"nodes": list(nodes.values()), "edges": edge_list}}

    def timeline(self, actor: Actor, entity: str) -> list[dict]:
        rows = self.db.ro_query(self.shared(actor), Q.ENTITY_TIMELINE, {"entity_id": entity_id(entity)})
        for r in rows:
            r["learned"] = ago(r["recorded_at"])
            r["ended"] = ago(r["valid_to"]) if r.get("valid_to") else None
        return rows

    def connect(self, actor: Actor, a: str, b: str) -> dict:
        """Shortest path between two memories or entities (FalkorDB algo.SPpaths)."""
        ida = a if label_for(a) != "Entity" else entity_id(a)
        idb = b if label_for(b) != "Entity" else entity_id(b)
        q = Q.CONNECT.replace("__LABEL_A__", label_for(ida)).replace("__LABEL_B__", label_for(idb))
        rows = self.db.ro_query(self.shared(actor), q, {"a": ida, "b": idb})
        if not rows:
            return {"connected": False, "note": f"No path between '{a}' and '{b}' within 6 hops."}
        p = rows[0]["path"]
        hops = []
        for i, e in enumerate(p["edges"]):
            hops.append(f"{_node_text(p['nodes'][i])} -[{e['type']}]- {_node_text(p['nodes'][i + 1])}")
        return {"connected": True, "length": len(p["edges"]), "path": hops,
                "nodes": [{"id": n.get("id"), "label": n["labels"][0], "text": _node_text(n)} for n in p["nodes"]]}

    # ------------------------------------------------------------ briefing

    def briefing(self, actor: Actor, max_facts: int = 10, max_procs: int = 6) -> dict:
        """What an agent should know when it starts: handoffs, live teammates, how-tos, key facts, recent changes."""
        graph = self.shared(actor)
        now = now_ms()
        inbox = self.inbox(actor)
        team = [t for t in self.team_status(actor) if not t["is_you"] or t["sessions"] > 1]
        procs = self.db.ro_query(graph, Q.TOP_PROCEDURES, {"limit": max_procs})
        facts = self.db.ro_query(graph, Q.TOP_FACTS, {"limit": max_facts, "as_of": now})
        changes = self.db.ro_query(graph, Q.RECENT_CHANGES, {"since": now - 7 * DAY, "limit": 5})
        private_facts = []
        if self.graph_exists(self.private(actor)):
            private_facts = self.db.ro_query(self.private(actor), Q.TOP_FACTS, {"limit": 5, "as_of": now})
        counts = {r["label"]: r["count"] for r in self.db.ro_query(graph, Q.COUNTS)}

        L = [f"Hivemind team memory for workspace '{actor.workspace}' "
             f"({counts.get('Fact', 0)} facts, {counts.get('Procedure', 0)} procedures, "
             f"{counts.get('Agent', 0)} agents). You are {actor.agent_id}."]
        if inbox:
            L.append("\nHandoffs waiting for you:")
            for h in inbox[:5]:
                L.append(f"- [{h['id']}] task '{h['task_title']}' from {h['from_agent']} ({h['when']}): {clip(h['summary'], 300)}")
                for s in (h.get("next_steps") or [])[:5]:
                    L.append(f"    next: {s}")
                for c in h["carried"][:5]:
                    L.append(f"    context [{c['id']}]: {clip(c['text'] or '', 200)}")
            L.append("  (accept with the accept_handoff tool)")
        if team:
            L.append("\nTeammates active right now:")
            for t in team[:6]:
                bits = []
                if t["tasks"]:
                    bits.append("working on " + "; ".join(t["tasks"][:2]))
                if t["files"]:
                    bits.append("editing " + ", ".join(t["files"][:4]))
                L.append(f"- {t['agent_id']} ({t['last_seen_ago']}): {' / '.join(bits) or 'active'}")
        if procs:
            L.append("\nKnown procedures (how-tos the team verified):")
            for p in procs:
                steps = " -> ".join(p["steps"] or [])
                tag = "auto-learned" if p.get("auto") else p.get("created_by")
                L.append(f"- [{p['id']}] {p['goal']}: {steps}  (worked {p['success_count']}x, failed "
                         f"{p['fail_count']}x; {tag})")
        if facts:
            L.append("\nKey facts:")
            for f in facts:
                L.append(f"- [{f['id']}] {f['statement']}  ({f['kind']}, {f['source_agent']}, {ago(f['recorded_at'])})")
        if private_facts:
            L.append("\nYour private notes:")
            for f in private_facts:
                L.append(f"- [{f['id']}] {f['statement']}")
        if changes:
            L.append("\nRecently changed (old belief -> new):")
            for c in changes:
                L.append(f"- '{clip(c['old_statement'], 120)}' -> '{clip(c['statement'], 120)}' ({c['by']}, {ago(c['at'])})")
        L.append("\nHivemind tools: recall, learn, supersede, record_procedure, find_procedure, report_outcome, "
                 "claim_task, handoff, inbox, team_status, why. Learn durable facts and procedures as you discover "
                 "them so teammates benefit.")
        text = "\n".join(L)
        return {"text": text, "inbox": inbox, "team": team, "procedures": procs, "facts": facts,
                "changes": changes, "counts": counts}

    # ------------------------------------------------------------ consolidation (graph algorithms)

    def consolidate(self, actor: Actor, archive_after_days: int = 30) -> dict:
        """Run graph algorithms over memory: PageRank importance, topic communities, archiving."""
        graph = self.shared(actor)
        now = now_ms()
        out: dict[str, Any] = {}
        out["entities_ranked"] = self.db.query(graph, Q.PAGERANK_ENTITIES)[0]["n"]
        out["facts_scored"] = self.db.query(graph, Q.FACT_IMPORTANCE)[0]["n"]
        # Topics: connected components of the entity graph; components too big to
        # be one topic are split with label propagation (CDLP).
        groups = []
        lp = None
        for comp in self.db.ro_query(graph, Q.COMPONENTS):
            members = list(zip(comp["ids"], comp["names"], comp["centralities"]))
            if len(members) <= self.MAX_TOPIC_SIZE:
                groups.append(members)
                continue
            if lp is None:
                lp = {i: c["community"] for c in self.db.ro_query(graph, Q.COMMUNITIES) for i in c["ids"]}
            split: dict[int, list] = {}
            for m in members:
                split.setdefault(lp.get(m[0], -1), []).append(m)
            groups.extend(split.values())
        self.db.query(graph, Q.CLEAR_TOPICS)
        topics = []
        for n, members in enumerate(g for g in groups if len(g) >= 2):
            ranked = sorted(members, key=lambda m: -(m[2] or 0))
            label = " / ".join(m[1] for m in ranked[:3])
            tid = f"topic_{n}"
            ids = [m[0] for m in members]
            self.db.query(graph, Q.CREATE_TOPIC, {"id": tid, "label": label, "size": len(ids), "ids": ids, "now": now})
            topics.append({"id": tid, "label": label, "size": len(ids)})
        out["topics"] = topics
        out["episodes_archived"] = self.db.query(graph, Q.ARCHIVE_EPISODES,
                                                 {"before": now - archive_after_days * DAY})[0]["n"]
        self._publish(actor, "memory.consolidated", topics=len(topics))
        return out

    # ------------------------------------------------------------ dashboard helpers

    def stats(self, actor: Actor) -> dict:
        out = {"team": {r["label"]: r["count"] for r in self.db.ro_query(self.shared(actor), Q.COUNTS)}}
        if self.graph_exists(self.private(actor)):
            out["private"] = {r["label"]: r["count"] for r in self.db.ro_query(self.private(actor), Q.COUNTS)}
        return out

    def list_workspaces(self) -> list[dict]:
        out: dict[str, dict] = {}
        for name in self.db.list_graphs():
            parsed = parse_graph_name(name)
            if not parsed:
                continue
            ws, user = parsed
            entry = out.setdefault(ws, {"workspace": ws, "private_graphs": []})
            if user:
                entry["private_graphs"].append(user)
        return sorted(out.values(), key=lambda x: x["workspace"])

    def graph_view(self, workspace: str, as_of: int | None = None, limit: int = 400, user: str | None = None,
                   with_topics: bool = True) -> dict:
        graph = private_graph_name(workspace, user) if user else shared_graph_name(workspace)
        as_of = int(as_of or now_ms())
        nodes = self.db.ro_query(graph, Q.GRAPH_NODES, {"as_of": as_of, "limit": limit, "with_topics": with_topics})
        ids = [n["id"] for n in nodes if n.get("id")]
        edges = self.db.ro_query(graph, Q.GRAPH_EDGES, {"ids": ids}) if ids else []
        for n in nodes:
            n["text"] = clip(str(n.get("text") or ""), 240)
            # A fact superseded after `as_of` was still true then.
            if n["label"] == "Fact" and n.get("valid_to") and n["valid_to"] > as_of and n["status"] == "superseded":
                n["status"] = "active"
        return {"graph": graph, "as_of": as_of, "nodes": nodes, "edges": edges}

    def node_detail(self, workspace: str, node_id: str, user: str | None = None) -> dict:
        graph = private_graph_name(workspace, user) if user else shared_graph_name(workspace)
        label = label_for(node_id)
        for candidate in [label] + (["User"] if label == "Entity" else []):  # users and entities share id style
            rows = self.db.ro_query(graph, _tpl(Q.NODE_DETAIL, candidate), {"id": node_id})
            if rows:
                return rows[0]["node"]
        return {}


def _node_text(n: dict) -> str:
    for k in ("statement", "goal", "text", "title", "summary", "name", "label"):
        if n.get(k):
            return clip(str(n[k]), 200)
    return str(n.get("id"))


def _why_story(node: dict, row: dict, by_internal: dict[int, dict]) -> list[str]:
    """Plain-English provenance lines from the WHY query's path groups."""
    lines = []
    label = node["labels"][0]
    status = node.get("status") or "active"
    lines.append(f"{label} '{_node_text(node)}' is {status}.")
    for p in row["origin"] or []:
        ep, sess, agent, user = p["nodes"][1], p["nodes"][2], p["nodes"][3], p["nodes"][4]
        lines.append(f"Learned by {agent.get('id')} (for {user.get('id')}) in session {sess.get('id')} "
                     f"{ago(ep.get('ts'))}, from {ep.get('kind')}: \"{clip(ep.get('text') or '', 160)}\"")
    learners = sorted({p["nodes"][-1].get("id") for p in row["learners"] or []})
    if len(learners) > 1:
        lines.append(f"Independently confirmed by {len(learners)} agents: {', '.join(learners)}.")
    for p in row["replaced"] or []:
        old = p["nodes"][-1]
        lines.append(f"It replaced: '{_node_text(old)}' ({old.get('status')}).")
    for p in row["replaced_by"] or []:
        new = p["nodes"][0]
        lines.append(f"It was replaced by: '{_node_text(new)}'.")
    about = sorted({_node_text(p["nodes"][-1]) for p in row["about"] or [] if "Entity" in p["nodes"][-1]["labels"]})
    if about:
        lines.append(f"About: {', '.join(about[:8])}.")
    for p in row["handoffs"] or []:
        lines.append(f"Passed along in a handoff from {p['nodes'][0].get('id')}.")
    uses = row["uses"] or []
    if uses:
        ok = sum(1 for p in uses if p["edges"][0].get("ok"))
        lines.append(f"Used in {len(uses)} session(s): {ok} succeeded, {len(uses) - ok} failed.")
    return lines
