"""The Cypher catalogue.

Every query Hivemind runs against FalkorDB lives here, parameterised. Agents
never write Cypher: they call typed tools, and the tools call these.

Graph model (one graph per workspace, plus one private graph per user):

  (:User)<-[:ACTS_FOR]-(:Agent)<-[:RUN_BY]-(:Session)
  (:Episode)-[:IN_SESSION]->(:Session)          episodic memory
  (:Episode)-[:NEXT]->(:Episode)                conversation history, in order
  (:Episode)-[:MENTIONS]->(:Entity)
  (:Fact)-[:ABOUT]->(:Entity)                   semantic memory
  (:Fact)-[:LEARNED_FROM]->(:Episode)           provenance ("why do we believe this?")
  (:Fact)-[:LEARNED_BY]->(:Agent)               who learned / reinforced it
  (:Fact)-[:SUPERSEDES]->(:Fact)                knowledge changing over time
  (:Procedure)-[:FOR]->(:Entity)                procedural memory
  (:Procedure)-[:LEARNED_FROM]->(:Episode)
  (:Procedure)-[:REVISES]->(:Procedure)
  (:Procedure)-[:USED_IN {ok}]->(:Session)      reinforcement from outcomes
  (:Task)-[:CLAIMED_BY]->(:Agent)               coordination
  (:Handoff)-[:OF]->(:Task), -[:FROM|TO]->(:Agent), -[:CARRIES]->(:Fact|:Procedure|:Episode)
  (:Session)-[:TOUCHED {at}]->(:Entity)         live presence: who is editing what
  (:Entity)-[:RELATES_TO {weight}]->(:Entity)   co-occurrence knowledge graph
  (:Entity)-[:IN_TOPIC]->(:Topic)               communities from label propagation

Facts are bi-temporal: `valid_from`/`valid_to` say when a fact was true,
`recorded_at` says when the team learned it. Nothing is overwritten; a new
fact SUPERSEDES the old one, so "what did we believe last Tuesday?" works.
"""

from __future__ import annotations

LABELS_WITH_ID = ["Agent", "User", "Session", "Episode", "Fact", "Procedure", "Entity", "Task", "Handoff", "Topic"]


def schema_statements(dim: int) -> list[str]:
    stmts = [f"CREATE INDEX FOR (n:{label}) ON (n.id)" for label in LABELS_WITH_ID]
    stmts += [
        "CREATE INDEX FOR (n:Fact) ON (n.key)",
        "CREATE INDEX FOR (n:Task) ON (n.status)",
        "CREATE INDEX FOR (n:Session) ON (n.status)",
        f"CREATE VECTOR INDEX FOR (n:Fact) ON (n.embedding) OPTIONS {{dimension:{dim}, similarityFunction:'cosine'}}",
        f"CREATE VECTOR INDEX FOR (n:Procedure) ON (n.embedding) OPTIONS {{dimension:{dim}, similarityFunction:'cosine'}}",
        f"CREATE VECTOR INDEX FOR (n:Episode) ON (n.embedding) OPTIONS {{dimension:{dim}, similarityFunction:'cosine'}}",
        "CALL db.idx.fulltext.createNodeIndex('Fact', 'statement')",
        "CALL db.idx.fulltext.createNodeIndex('Episode', 'text')",
        "CALL db.idx.fulltext.createNodeIndex('Procedure', 'goal')",
    ]
    return stmts


# A fact is visible "as of" a moment if we had learned it by then, it had
# started being true, it had not yet been superseded, and it was not retracted.
def valid_at(v: str = "f") -> str:
    return (f"({v}.recorded_at <= $as_of AND {v}.valid_from <= $as_of "
            f"AND ({v}.valid_to IS NULL OR {v}.valid_to > $as_of) "
            f"AND NOT {v}.status IN ['retracted', 'promoted'])")


FACT_COLS = """f.id AS id, f.statement AS statement, f.kind AS kind, f.key AS key,
  f.confidence AS confidence, f.valid_from AS valid_from, f.valid_to AS valid_to,
  f.recorded_at AS recorded_at, f.status AS status, f.uses AS uses,
  f.importance AS importance, f.source_agent AS source_agent"""

PROC_COLS = """p.id AS id, p.goal AS goal, p.steps AS steps, p.success_count AS success_count,
  p.fail_count AS fail_count, p.last_used AS last_used, p.created_at AS created_at,
  p.created_by AS created_by, p.auto AS auto, p.status AS status"""

EPISODE_COLS = """e.id AS id, e.kind AS kind, e.text AS text, e.ts AS ts,
  e.agent_id AS agent_id, e.importance AS importance"""

# ---------------------------------------------------------------- sessions

UPSERT_SESSION = """
MERGE (u:User {id: $user})
  ON CREATE SET u.created_at = $now
MERGE (a:Agent {id: $agent_id})
  ON CREATE SET a.created_at = $now, a.client = $client, a.user = $user
SET a.last_seen = $now, a.role = coalesce($role, a.role)
MERGE (a)-[:ACTS_FOR]->(u)
MERGE (s:Session {id: $session_id})
  ON CREATE SET s.started_at = $now, s.agent_id = $agent_id, s.user = $user,
                s.cwd = $cwd, s.branch = $branch, s.client = $client
SET s.last_seen = $now, s.status = 'active'
MERGE (s)-[:RUN_BY]->(a)
RETURN s.id AS id, s.started_at AS started_at
"""

LATEST_ACTIVE_SESSION = """
MATCH (s:Session)-[:RUN_BY]->(:Agent {id: $agent_id})
WHERE s.status = 'active' AND s.last_seen >= $since
RETURN s.id AS id ORDER BY s.last_seen DESC LIMIT 1
"""

END_SESSION = """
MATCH (s:Session {id: $session_id})
SET s.status = 'ended', s.ended_at = $now, s.end_reason = $reason
RETURN s.id AS id
"""

SESSION_STATE = """
MATCH (s:Session {id: $session_id})
RETURN s.fail_key AS fail_key, s.fail_cmd AS fail_cmd, s.fail_episode AS fail_episode,
       s.steps_since_fail AS steps_since_fail
"""

SET_FAIL_STATE = """
MATCH (s:Session {id: $session_id})
SET s.fail_key = $fail_key, s.fail_cmd = $fail_cmd, s.fail_episode = $fail_episode,
    s.steps_since_fail = $steps
"""

CLEAR_FAIL_STATE = """
MATCH (s:Session {id: $session_id})
REMOVE s.fail_key, s.fail_cmd, s.fail_episode, s.steps_since_fail
"""

# ---------------------------------------------------------------- episodic memory

ADD_EPISODE = """
MATCH (s:Session {id: $session_id})
CREATE (e:Episode {id: $id, ts: $now, kind: $kind, text: $text, importance: $importance,
                   agent_id: $agent_id, session_id: $session_id, embedding: vecf32($embedding)})
CREATE (e)-[:IN_SESSION]->(s)
WITH s, e
OPTIONAL MATCH (prev:Episode) WHERE prev.id = s.last_episode_id
FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT]->(e))
SET s.last_episode_id = $id, s.last_seen = $now
FOREACH (ent IN $entities |
  MERGE (x:Entity {id: ent.id})
    ON CREATE SET x.name = ent.name, x.type = ent.type, x.created_at = $now
  MERGE (e)-[:MENTIONS]->(x))
RETURN e.id AS id
"""

MERGE_ENTITIES = """
UNWIND $entities AS ent
MERGE (x:Entity {id: ent.id})
  ON CREATE SET x.name = ent.name, x.type = ent.type, x.created_at = $now
"""

LINK_ENTITIES = """
UNWIND $pairs AS p
MATCH (a:Entity {id: p[0]}), (b:Entity {id: p[1]})
MERGE (a)-[r:RELATES_TO]->(b)
  ON CREATE SET r.weight = 1, r.since = $now
  ON MATCH SET r.weight = r.weight + 1
"""

VECTOR_EPISODES = f"""
CALL db.idx.vector.queryNodes('Episode', 'embedding', $k, vecf32($embedding)) YIELD node AS e, score
WHERE e.ts <= $as_of AND NOT e.kind IN $exclude_kinds AND coalesce(e.status, 'active') <> 'forgotten'
RETURN {EPISODE_COLS}, 1.0 - score AS sim
"""

FULLTEXT_EPISODES = f"""
CALL db.idx.fulltext.queryNodes('Episode', $q) YIELD node AS e, score
WHERE e.ts <= $as_of AND NOT e.kind IN $exclude_kinds AND coalesce(e.status, 'active') <> 'forgotten'
RETURN {EPISODE_COLS}, score AS fts
LIMIT $k
"""

HISTORY = f"""
MATCH (e:Episode)-[:IN_SESSION]->(s:Session)
WHERE ($session_id IS NULL OR s.id = $session_id)
  AND ($agent_id IS NULL OR e.agent_id = $agent_id)
  AND ($user IS NULL OR s.user = $user)
  AND e.kind IN $kinds AND coalesce(e.status, 'active') <> 'forgotten'
RETURN {EPISODE_COLS}, s.id AS session_id
ORDER BY e.ts DESC LIMIT $limit
"""

# ---------------------------------------------------------------- semantic memory

ADD_FACT = """
MATCH (a:Agent {id: $agent_id})
OPTIONAL MATCH (src:Episode {id: $episode_id})
CREATE (f:Fact {id: $id, statement: $statement, kind: $kind, key: $key, confidence: $confidence,
                valid_from: $valid_from, recorded_at: $now, status: 'active', uses: 0,
                importance: 0.0, source_agent: $agent_id, scope: $scope,
                promoted_from: $promoted_from, embedding: vecf32($embedding)})
CREATE (f)-[:LEARNED_BY {at: $now}]->(a)
FOREACH (_ IN CASE WHEN src IS NULL THEN [] ELSE [1] END | CREATE (f)-[:LEARNED_FROM]->(src))
FOREACH (ent IN $entities |
  MERGE (x:Entity {id: ent.id})
    ON CREATE SET x.name = ent.name, x.type = ent.type, x.created_at = $now
  CREATE (f)-[:ABOUT]->(x))
RETURN f.id AS id
"""

ACTIVE_FACT_BY_KEY = f"""
MATCH (f:Fact {{key: $key}})
WHERE f.valid_to IS NULL AND f.status = 'active'
RETURN {FACT_COLS}
"""

VECTOR_FACTS = f"""
CALL db.idx.vector.queryNodes('Fact', 'embedding', $k, vecf32($embedding)) YIELD node AS f, score
WHERE {valid_at('f')}
RETURN {FACT_COLS}, 1.0 - score AS sim
"""

FULLTEXT_FACTS = f"""
CALL db.idx.fulltext.queryNodes('Fact', $q) YIELD node AS f, score
WHERE {valid_at('f')}
RETURN {FACT_COLS}, score AS fts
LIMIT $k
"""

# Graph expansion: facts about the entities named in the query, and about
# their direct neighbours in the co-occurrence graph (one hop).
ENTITY_FACTS = f"""
MATCH (seed:Entity) WHERE seed.id IN $entity_ids
MATCH path = (seed)-[:RELATES_TO*0..1]-(x:Entity)<-[:ABOUT]-(f:Fact)
WHERE {valid_at('f')}
WITH f, min(length(path)) AS hops, collect(DISTINCT x.name) AS via
RETURN {FACT_COLS}, hops, via
LIMIT $k
"""

REINFORCE_FACT = """
MATCH (f:Fact {id: $id}), (a:Agent {id: $agent_id})
SET f.confidence = CASE WHEN f.confidence + 0.05 > 1.0 THEN 1.0 ELSE f.confidence + 0.05 END,
    f.reinforced_at = $now
MERGE (f)-[r:LEARNED_BY]->(a)
  ON CREATE SET r.at = $now
RETURN f.id AS id, f.confidence AS confidence
"""

SUPERSEDE_FACT = """
MATCH (old:Fact {id: $old_id}), (new:Fact {id: $new_id})
SET old.valid_to = $now, old.status = 'superseded', old.superseded_by = $new_id
CREATE (new)-[:SUPERSEDES {at: $now, reason: $reason, by: $agent_id}]->(old)
RETURN old.statement AS statement
"""

# Queries below that act on "any memory" are templates: __LABEL__ is replaced
# with a whitelisted label (see core.label_for), so the id lookup uses the
# per-label index. FalkorDB labels cannot be query parameters.

RETRACT = """
MATCH (n:__LABEL__ {id: $id})
SET n.status = CASE WHEN n:Episode THEN 'forgotten' ELSE 'retracted' END,
    n.valid_to = coalesce(n.valid_to, $now), n.retracted_reason = $reason, n.retracted_by = $agent_id
RETURN labels(n)[0] AS label, coalesce(n.statement, n.goal, n.text) AS text
"""

# Hard delete ("right to be forgotten"): the node, plus any fact or procedure
# whose only provenance was this node.
HARD_DELETE = """
MATCH (n:__LABEL__ {id: $id})
OPTIONAL MATCH (d)-[:LEARNED_FROM]->(n)
OPTIONAL MATCH (d)-[:LEARNED_FROM]->(src)
WITH n, d, count(DISTINCT src) AS sources
WITH n, collect(CASE WHEN sources = 1 THEN d END) AS derived
FOREACH (x IN derived | DETACH DELETE x)
WITH n, size(derived) AS derived_count
DETACH DELETE n
RETURN derived_count
"""

MARK_PROMOTED = """
MATCH (f:Fact {id: $id})
SET f.status = 'promoted', f.promoted_to = $new_id, f.promoted_at = $now
"""

GET_FACT = f"""
MATCH (f:Fact {{id: $id}})
OPTIONAL MATCH (f)-[:ABOUT]->(x:Entity)
RETURN {FACT_COLS}, f.scope AS scope, collect(x.name) AS entities
"""

EXISTS_NODE = """
MATCH (n:__LABEL__ {id: $id})
RETURN n.id AS id
"""

BUMP_USES = """
UNWIND $ids AS nid
MATCH (n:__LABEL__ {id: nid})
SET n.uses = coalesce(n.uses, 0) + 1, n.last_recalled = $now
"""

PROVENANCE = """
UNWIND $ids AS nid
MATCH (f:__LABEL__ {id: nid})
OPTIONAL MATCH (f)-[:LEARNED_FROM]->(ep:Episode)
OPTIONAL MATCH (ep)-[:IN_SESSION]->(s:Session)
OPTIONAL MATCH (f)-[:LEARNED_BY]->(a:Agent)
OPTIONAL MATCH (f)-[:ABOUT|FOR]->(x:Entity)
RETURN f.id AS id, collect(DISTINCT a.id) AS agents, collect(DISTINCT x.name) AS entities,
       head(collect(ep.text)) AS source_text, head(collect(ep.kind)) AS source_kind,
       head(collect(ep.ts)) AS source_ts, head(collect(s.id)) AS source_session
"""

# Everything that explains a memory: where it came from, who learned it,
# what it replaced, what replaced it, and which handoffs carried it.
# Each OPTIONAL MATCH is collected before the next to avoid a cartesian blow-up.
WHY = """
MATCH (n:__LABEL__ {id: $id})
OPTIONAL MATCH p = (n)-[:LEARNED_FROM]->(:Episode)-[:IN_SESSION]->(:Session)-[:RUN_BY]->(:Agent)-[:ACTS_FOR]->(:User)
WITH n, collect(DISTINCT p) AS origin
OPTIONAL MATCH p = (n)-[:SUPERSEDES|REVISES*1..10]->()
WITH n, origin, collect(DISTINCT p) AS replaced
OPTIONAL MATCH p = ()-[:SUPERSEDES|REVISES*1..10]->(n)
WITH n, origin, replaced, collect(DISTINCT p) AS replaced_by
OPTIONAL MATCH p = (n)-[:LEARNED_BY]->(:Agent)
WITH n, origin, replaced, replaced_by, collect(DISTINCT p) AS learners
OPTIONAL MATCH p = (n)-[:ABOUT|FOR|MENTIONS|IN_SESSION]->()
WITH n, origin, replaced, replaced_by, learners, collect(DISTINCT p) AS about
OPTIONAL MATCH p = (:Agent)<-[:FROM]-(:Handoff)-[:CARRIES]->(n)
WITH n, origin, replaced, replaced_by, learners, about, collect(DISTINCT p) AS handoffs
OPTIONAL MATCH p = (n)-[:USED_IN]->(:Session)
RETURN n AS node, origin, replaced, replaced_by, learners, about, handoffs, collect(DISTINCT p) AS uses
"""

# How knowledge about one entity evolved: every fact, including superseded ones.
ENTITY_TIMELINE = f"""
MATCH (x:Entity {{id: $entity_id}})<-[:ABOUT]-(f:Fact)
OPTIONAL MATCH (f)-[s:SUPERSEDES]->(old:Fact)
RETURN {FACT_COLS}, old.id AS supersedes, s.reason AS reason
ORDER BY f.recorded_at ASC
"""

# Explain how two things are connected with FalkorDB's shortest-path algorithm.
CONNECT = """
MATCH (a:__LABEL_A__ {id: $a}), (b:__LABEL_B__ {id: $b})
CALL algo.SPpaths({sourceNode: a, targetNode: b,
                   relTypes: ['RELATES_TO', 'ABOUT', 'MENTIONS', 'FOR', 'LEARNED_FROM', 'IN_SESSION', 'RUN_BY', 'TOUCHED'],
                   relDirection: 'both', maxLen: 6, pathCount: 1})
YIELD path
RETURN path
"""

# ---------------------------------------------------------------- procedural memory

ADD_PROCEDURE = """
MATCH (a:Agent {id: $agent_id})
CREATE (p:Procedure {id: $id, goal: $goal, steps: $steps, success_count: $success, fail_count: $fail,
                     created_at: $now, last_used: $now, created_by: $agent_id, auto: $auto,
                     status: 'active', uses: 0, embedding: vecf32($embedding)})
CREATE (p)-[:LEARNED_BY {at: $now}]->(a)
FOREACH (ent IN $entities |
  MERGE (x:Entity {id: ent.id})
    ON CREATE SET x.name = ent.name, x.type = ent.type, x.created_at = $now
  CREATE (p)-[:FOR]->(x))
WITH p
OPTIONAL MATCH (old:Procedure {id: $revises})
FOREACH (_ IN CASE WHEN old IS NULL THEN [] ELSE [1] END | CREATE (p)-[:REVISES {at: $now}]->(old))
RETURN p.id AS id
"""

LINK_SOURCES = """
UNWIND $episode_ids AS eid
MATCH (n:__LABEL__ {id: $id}), (ep:Episode {id: eid})
CREATE (n)-[:LEARNED_FROM]->(ep)
"""

VECTOR_PROCEDURES = f"""
CALL db.idx.vector.queryNodes('Procedure', 'embedding', $k, vecf32($embedding)) YIELD node AS p, score
WHERE p.status = 'active' AND p.created_at <= $as_of
RETURN {PROC_COLS}, 1.0 - score AS sim
"""

PROCEDURES_FOR_ENTITY = f"""
MATCH (p:Procedure)-[:FOR]->(x:Entity)
WHERE x.id IN $entity_ids AND p.status = 'active'
RETURN DISTINCT {PROC_COLS}
"""

PROCEDURE_OUTCOME = """
MATCH (p:Procedure {id: $id})
SET p.success_count = p.success_count + $success, p.fail_count = p.fail_count + $fail, p.last_used = $now
WITH p
OPTIONAL MATCH (s:Session {id: $session_id})
FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END |
  CREATE (p)-[:USED_IN {ok: $ok, at: $now, notes: $notes}]->(s))
RETURN p.success_count AS success_count, p.fail_count AS fail_count
"""

# ---------------------------------------------------------------- coordination

CREATE_TASK = """
MATCH (a:Agent {id: $agent_id})
CREATE (t:Task {id: $id, title: $title, description: $description, status: 'open',
                created_at: $now, updated_at: $now, created_by: $agent_id})
CREATE (t)-[:CREATED_BY]->(a)
FOREACH (ent IN $entities |
  MERGE (x:Entity {id: ent.id})
    ON CREATE SET x.name = ent.name, x.type = ent.type, x.created_at = $now
  MERGE (t)-[:TOUCHES]->(x))
RETURN t.id AS id
"""

# Atomic claim. FalkorDB runs writes to one graph one at a time, so this single
# query is a race-free compare-and-set: of N agents claiming at once, one wins.
CLAIM_TASK = """
MATCH (t:Task {id: $task_id})
WHERE t.status IN ['open', 'handed_off']
   OR (t.status = 'claimed' AND (t.claimed_by = $agent_id OR t.heartbeat < $stale_before))
MATCH (a:Agent {id: $agent_id})
OPTIONAL MATCH (t)-[old:CLAIMED_BY]->()
DELETE old
WITH DISTINCT t, a
SET t.status = 'claimed', t.claimed_by = $agent_id, t.heartbeat = $now, t.updated_at = $now
CREATE (t)-[:CLAIMED_BY {at: $now}]->(a)
RETURN t.id AS id, t.title AS title
"""

TASK_INFO = """
MATCH (t:Task {id: $task_id})
OPTIONAL MATCH (t)-[:TOUCHES]->(x:Entity)
RETURN t.id AS id, t.title AS title, t.description AS description, t.status AS status,
       t.claimed_by AS claimed_by, t.heartbeat AS heartbeat, t.created_by AS created_by,
       collect(x.name) AS entities
"""

FIND_TASKS = """
MATCH (t:Task)
WHERE ($status IS NULL OR t.status = $status)
RETURN t.id AS id, t.title AS title, t.description AS description, t.status AS status,
       t.claimed_by AS claimed_by, t.updated_at AS updated_at, t.created_by AS created_by
ORDER BY t.updated_at DESC LIMIT $limit
"""

COMPLETE_TASK = """
MATCH (t:Task {id: $task_id})
SET t.status = 'done', t.updated_at = $now, t.completed_by = $agent_id, t.result = $summary
RETURN t.id AS id, t.title AS title
"""

CREATE_HANDOFF = """
MATCH (t:Task {id: $task_id}), (from:Agent {id: $agent_id})
OPTIONAL MATCH (t)-[c:CLAIMED_BY]->()
DELETE c
WITH DISTINCT t, from
CREATE (h:Handoff {id: $id, ts: $now, summary: $summary, next_steps: $next_steps,
                   status: 'pending', to_role: $to_role, to_agent: $to_agent, from_agent: $agent_id})
CREATE (h)-[:OF]->(t), (h)-[:FROM]->(from)
SET t.status = 'handed_off', t.updated_at = $now, t.claimed_by = null
WITH h
OPTIONAL MATCH (to:Agent {id: $to_agent})
FOREACH (_ IN CASE WHEN to IS NULL THEN [] ELSE [1] END | CREATE (h)-[:TO]->(to))
RETURN h.id AS id
"""

CARRY = """
UNWIND $ids AS cid
MATCH (h:Handoff {id: $handoff_id}), (c:__LABEL__ {id: cid})
CREATE (h)-[:CARRIES]->(c)
"""

INBOX = """
MATCH (h:Handoff {status: 'pending'})-[:OF]->(t:Task)
WHERE h.from_agent <> $agent_id
  AND (h.to_agent = $agent_id OR ($role IS NOT NULL AND h.to_role = $role)
       OR (h.to_agent IS NULL AND h.to_role IS NULL))
OPTIONAL MATCH (h)-[:CARRIES]->(c)
RETURN h.id AS id, h.ts AS ts, h.summary AS summary, h.next_steps AS next_steps,
       h.from_agent AS from_agent, h.to_agent AS to_agent, h.to_role AS to_role,
       t.id AS task_id, t.title AS task_title,
       collect({id: c.id, text: coalesce(c.statement, c.goal, c.text)}) AS carried
ORDER BY h.ts DESC
"""

ACCEPT_HANDOFF = """
MATCH (h:Handoff {id: $id})-[:OF]->(t:Task), (a:Agent {id: $agent_id})
WHERE h.status = 'pending'
SET h.status = 'accepted', h.accepted_by = $agent_id, h.accepted_at = $now
MERGE (h)-[:ACCEPTED_BY]->(a)
RETURN t.id AS task_id
"""

TOUCH = """
MATCH (s:Session {id: $session_id})
MERGE (x:Entity {id: $entity_id})
  ON CREATE SET x.name = $name, x.type = 'file', x.created_at = $now
MERGE (s)-[r:TOUCHED]->(x)
SET r.at = $now, r.count = coalesce(r.count, 0) + 1, s.last_seen = $now
"""

# Who else (another live session, possibly the same human in another window)
# touched this file recently?
FILE_CONFLICTS = """
MATCH (x:Entity {id: $entity_id})<-[r:TOUCHED]-(s:Session)-[:RUN_BY]->(a:Agent)
WHERE r.at >= $since AND s.id <> $session_id AND s.status = 'active'
OPTIONAL MATCH (t:Task {status: 'claimed'})-[:CLAIMED_BY]->(a)
RETURN a.id AS agent_id, s.id AS session_id, r.at AS at, collect(DISTINCT t.title) AS tasks
ORDER BY r.at DESC
"""

TEAM_STATUS = """
MATCH (a:Agent) WHERE a.last_seen >= $since
OPTIONAL MATCH (t:Task {status: 'claimed'})-[:CLAIMED_BY]->(a)
OPTIONAL MATCH (s:Session {status: 'active'})-[:RUN_BY]->(a)
OPTIONAL MATCH (s)-[r:TOUCHED]->(x:Entity) WHERE r.at >= $touch_since
RETURN a.id AS agent_id, a.client AS client, a.role AS role, a.last_seen AS last_seen,
       collect(DISTINCT t.title) AS tasks, collect(DISTINCT x.name) AS files,
       count(DISTINCT s) AS sessions
ORDER BY a.last_seen DESC
"""

# ---------------------------------------------------------------- briefing

TOP_FACTS = f"""
MATCH (f:Fact)
WHERE {valid_at('f')}
RETURN {FACT_COLS}
ORDER BY f.importance DESC, f.confidence DESC, f.recorded_at DESC
LIMIT $limit
"""

TOP_PROCEDURES = f"""
MATCH (p:Procedure {{status: 'active'}})
RETURN {PROC_COLS}
ORDER BY (p.success_count + 1.0) / (p.success_count + p.fail_count + 2.0) DESC, p.last_used DESC
LIMIT $limit
"""

RECENT_CHANGES = """
MATCH (new:Fact)-[s:SUPERSEDES]->(old:Fact)
WHERE s.at >= $since
RETURN new.id AS id, new.statement AS statement, old.statement AS old_statement, s.at AS at, s.by AS by
ORDER BY s.at DESC LIMIT $limit
"""

COUNTS = """
MATCH (n)
RETURN labels(n)[0] AS label, count(n) AS count
"""

# ---------------------------------------------------------------- algorithms

# Entity centrality: entities that many others relate to are "load-bearing"
# parts of the codebase; facts about them matter more.
PAGERANK_ENTITIES = """
CALL algo.pageRank('Entity', 'RELATES_TO') YIELD node, score
SET node.centrality = score
RETURN count(node) AS n
"""

FACT_IMPORTANCE = """
MATCH (f:Fact) WHERE f.status = 'active'
OPTIONAL MATCH (f)-[:ABOUT]->(x:Entity)
OPTIONAL MATCH (f)-[:LEARNED_BY]->(a:Agent)
WITH f, coalesce(max(x.centrality), 0.0) AS c, count(DISTINCT a) AS learners
SET f.importance = c * 10.0 + 0.15 * learners + 0.05 * coalesce(f.uses, 0) + 0.2 * f.confidence
RETURN count(f) AS n
"""

# Topics, step 1: weakly connected components of the entity graph.
COMPONENTS = """
CALL algo.WCC({nodeLabels: ['Entity'], relationshipTypes: ['RELATES_TO']})
YIELD node, componentId
RETURN componentId AS component, collect(node.id) AS ids, collect(node.name) AS names,
       collect(coalesce(node.centrality, 0.0)) AS centralities
"""

# Topics, step 2: split large components into communities with label propagation.
COMMUNITIES = """
CALL algo.labelPropagation({nodeLabels: ['Entity'], relationshipTypes: ['RELATES_TO']})
YIELD node, communityId
RETURN communityId AS community, collect(node.id) AS ids, collect(node.name) AS names,
       collect(coalesce(node.centrality, 0.0)) AS centralities
"""

CLEAR_TOPICS = """
MATCH (t:Topic) DETACH DELETE t
"""

CREATE_TOPIC = """
CREATE (t:Topic {id: $id, label: $label, size: $size, created_at: $now})
WITH t
UNWIND $ids AS eid
MATCH (x:Entity {id: eid})
CREATE (x)-[:IN_TOPIC]->(t)
RETURN count(x) AS n
"""

# Old, low-value episodes stop being retrieved once nothing derives from them.
ARCHIVE_EPISODES = """
MATCH (e:Episode)
WHERE e.ts < $before AND e.kind IN ['action', 'response', 'edit'] AND coalesce(e.status, 'active') = 'active'
  AND NOT ()-[:LEARNED_FROM|CARRIES]->(e)
SET e.status = 'forgotten'
RETURN count(e) AS n
"""

# ---------------------------------------------------------------- dashboard

GRAPH_NODES = """
MATCH (n)
WHERE NOT n:Topic OR $with_topics
WITH n, coalesce(n.recorded_at, n.ts, n.created_at, n.started_at, 0) AS t
WHERE t <= $as_of
RETURN labels(n)[0] AS label, n.id AS id,
       coalesce(n.statement, n.goal, n.text, n.title, n.summary, n.name, n.label, n.id) AS text,
       t AS t, n.status AS status, n.valid_to AS valid_to, n.kind AS kind, n.type AS type,
       n.importance AS importance, n.centrality AS centrality, n.agent_id AS agent_id,
       n.source_agent AS source_agent, n.created_by AS created_by
ORDER BY t DESC
LIMIT $limit
"""

GRAPH_EDGES = """
MATCH (a)-[r]->(b)
WHERE a.id IN $ids AND b.id IN $ids
RETURN labels(a)[0] AS src_label, a.id AS src, type(r) AS type, labels(b)[0] AS dst_label, b.id AS dst
"""

NODE_DETAIL = """
MATCH (n:__LABEL__ {id: $id})
RETURN n AS node
"""
