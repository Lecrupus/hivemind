"use strict";

/* ================================================================ helpers */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clip = (s, n) => { s = String(s ?? ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const restart = (el, cls) => { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); };
const mq = (q) => window.matchMedia(q);
const isDrawer = () => mq("(max-width: 1199px)").matches;
const isPhone = () => mq("(max-width: 759px)").matches;

async function api(path, opts) {
  let r;
  try { r = await fetch(path, opts); } catch (err) { setOffline("server"); throw err; }
  if (r.status === 503) { setOffline("falkordb"); throw new Error(`503 ${path}`); }
  // A non-database request succeeding proves the server is up, not that FalkorDB is;
  // a FalkorDB outage is cleared only by the health poll below.
  if (offlineReason === "server") setOffline(null);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}
// While the server or FalkorDB is unreachable, show why and poll until it's back, then reload the data.
let offlinePoll = null;
let offlineReason = null;
const OFFLINE_TEXT = {
  falkordb: "Can't reach FalkorDB, so memory is unavailable. Retrying automatically…",
  server: "Can't reach the Hivemind server. Retrying automatically…",
};
function setOffline(reason) {
  const b = document.getElementById("offline");
  if (!b) return;
  offlineReason = reason;
  b.hidden = !reason;
  if (reason) {
    $("#offline-text").textContent = OFFLINE_TEXT[reason];
    if (!offlinePoll) offlinePoll = setInterval(async () => {
      try {
        const h = await (await fetch("/api/health")).json();
        if (h.falkordb) { clearInterval(offlinePoll); offlinePoll = null; offlineReason = null; b.hidden = true; refreshAll(); }
        else $("#offline-text").textContent = OFFLINE_TEXT.falkordb;
      } catch { /* server still down */ }
    }, 4000);
  }
}
function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, (Date.now() - ts) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
const fmtTime = (ts) => new Date(ts).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const TYPE_VAR = {
  Agent: "--t-agent", Fact: "--t-fact", Procedure: "--t-procedure", Episode: "--t-episode", Task: "--t-task",
  Handoff: "--t-handoff", Entity: "--t-entity", Topic: "--t-topic", Session: "--t-session", User: "--t-user",
};
const typeColor = (label) => cssVar(TYPE_VAR[label] || "--t-entity");
// Client identity colours: solid squares carrying white initials (each ≥4.5:1 against white).
const CLIENTS = {
  "claude-code": { name: "Claude Code", color: "#b4532d" },
  cursor: { name: "Cursor", color: "#2d68ab" },
  codex: { name: "Codex", color: "#0b7458" },
  hivemind: { name: "Hivemind", color: "#5f5f59" },
};
const clientOf = (agentId) => (agentId || "").split("@")[0];
const userOf = (agentId) => (agentId || "").split("@")[1] || agentId || "?";
const client = (agentId) => CLIENTS[clientOf(agentId)] || { name: clientOf(agentId) || "Agent", color: "#6447b8" };
function avatar(agentId, size = "") {
  const u = userOf(agentId);
  const initials = u.length <= 2 ? u.toUpperCase() : u[0].toUpperCase();
  return `<span class="avatar ${size}" style="background:${client(agentId).color}" title="${esc(agentId)}" aria-hidden="true">${esc(initials)}</span>`;
}
const ticketId = (id) => "HM-" + String(id || "").replace(/^t_/, "").slice(0, 4).toUpperCase();
const STATUS = {
  open: ["Open", "open"], claimed: ["In progress", "ink"], handed_off: ["Handed off", "blue"], done: ["Done", "green"],
  pending: ["Pending", "amber"], accepted: ["Accepted", "green"], active: ["Active", "green"],
  superseded: ["Superseded", "struck"], retracted: ["Retracted", "signal"], promoted: ["Promoted", "blue"], ended: ["Ended", "plain"],
};
const badge = (status) => { const [t, c] = STATUS[status] || [status, "plain"]; return `<span class="tag ${c}">${esc(t)}</span>`; };
const keyOf = (label, id) => `${label}:${id}`;

const state = {
  ws: new URLSearchParams(location.search).get("workspace") || "demo",
  view: "map",
  asOf: null,
  range: { min: null, max: null },
  data: { nodes: [], edges: [] },
  team: { agents: [], tasks: [], handoffs: [] },
  mapLinks: [],
  desig: new Map(),
  seen: new Set(),
  firstRender: true,
  selected: null,
  pinned: null, // highlight set from Why?
  hiddenTypes: new Set(["Session", "User"]),
  steps: [],
  stats: null,
};
let explorer = null; // the force-graph instance, created on first visit to the Graph view

/* ================================================================ tabs (views + inspector) */
function setupTabs(list, onSelect) {
  const tabs = $$('[role="tab"]', list);
  const ind = $(".tab-ind", list);
  const move = () => {
    const a = tabs.find((t) => t.getAttribute("aria-selected") === "true");
    if (!a || !ind || !a.offsetWidth) return;
    ind.style.width = a.offsetWidth + "px";
    ind.style.transform = `translateX(${a.offsetLeft}px)`;
  };
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => onSelect(t));
    t.addEventListener("keydown", (e) => {
      const k = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (k === undefined) return;
      e.preventDefault();
      const next = tabs[(k + tabs.length) % tabs.length];
      next.focus(); onSelect(next);
    });
  });
  new ResizeObserver(move).observe(list);
  return {
    activate(match) { tabs.forEach((t) => { const on = match(t); t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1; }); move(); },
    move,
  };
}
const viewTabs = setupTabs($(".views"), (t) => setView(t.dataset.view));
const inspTabs = setupTabs($(".insp-tabs"), (t) => tab(t.dataset.tab));

/* ================================================================ theme */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("hm-theme-v2", t); } catch { /* storage unavailable */ }
  const dark = t === "dark";
  $("#theme").innerHTML = icon(dark ? "sun" : "moon");
  $("#theme").setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  if (explorer) explorer.refresh();
}
$("#theme").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
applyTheme(document.documentElement.dataset.theme || "light");

/* ================================================================ data loading */
async function loadGraph() {
  const q = new URLSearchParams({ workspace: state.ws, limit: 900 });
  if (state.asOf) q.set("as_of", state.asOf);
  state.data = await api(`/api/graph?${q}`);
  renderMap();
  if (explorer && state.view === "graph") explorer.load(state.data);
}
async function loadTeam() {
  state.team = await api(`/api/team?workspace=${state.ws}`);
  renderAgents(); renderQueue(); renderBoard();
}

const STAT_CELLS = [
  ["facts", "Facts", "Fact"], ["procs", "Procedures", "Procedure"], ["episodes", "Episodes", "Episode"], ["agents", "Agents", "Agent"],
  ["tasks", "Tasks", "Task"], ["handoffs", "Handoffs", "Handoff"], ["topics", "Topics", "Topic"],
];
async function loadStats() {
  const s = await api(`/api/stats?workspace=${state.ws}`);
  const t = s.team || {};
  const recent = s.recent || {};
  const el = $("#metrics");
  if (!el.children.length) {
    el.innerHTML = STAT_CELLS.map(([id, name]) => `
      <div class="stat" id="stat-${id}"><div class="stat-label">${name}</div>
        <div class="stat-row"><span class="stat-value">0</span><span class="stat-delta"></span></div></div>`).join("") + `
      <div class="stat key" id="stat-assists" title="Times an agent was handed the team's verified fix at the moment it failed">
        <div class="stat-label">Known fixes served</div>
        <div class="stat-row"><span class="stat-value">0</span><span class="stat-delta"></span></div></div>`;
  }
  el.classList.remove("loading");
  const set = (id, value, delta) => {
    const cell = $(`#stat-${id}`);
    const v = $(".stat-value", cell), d = $(".stat-delta", cell);
    const next = (value || 0).toLocaleString();
    // Values change in their fixed cells; nothing reflows while the demo runs.
    if (v.textContent !== next) { v.textContent = next; if (state.stats) restart(v, "changed"); }
    d.innerHTML = delta ? `+${delta}<span class="long"> last hour</span>` : "";
    d.classList.toggle("up", !!delta);
  };
  STAT_CELLS.forEach(([id, , label]) => set(id, t[label], recent[label]));
  set("assists", s.assists, s.recent_assists);
  state.stats = s;
}
async function loadRange() {
  try {
    const r = await api(`/api/time-range?workspace=${state.ws}`);
    state.range = { min: r.min, max: Math.max(r.max || 0, Date.now()) };
  } catch { state.range = { min: null, max: null }; }
  setRulerStart();
}

let refreshTimer;
function scheduleRefresh(delay = 300) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    if (!state.asOf) loadGraph().catch(console.error);
    loadTeam().catch(console.error); loadStats().catch(console.error); loadRange();
  }, delay);
}

/* ================================================================ agents and queue */
function renderAgents() {
  // Same order as the map: by designation, so A1 is A1 everywhere.
  const num = (a) => +(state.desig.get(keyOf("Agent", a.agent_id)) || "A999").slice(1);
  const agents = [...(state.team.agents || [])].sort((a, b) => num(a) - num(b));
  $("#agent-count").textContent = agents.length || "";
  $("#agents").innerHTML = agents.length ? agents.map((a) => {
    const live = Date.now() - a.last_seen < 5 * 60_000;
    const c = client(a.agent_id);
    const key = keyOf("Agent", a.agent_id);
    const work = a.tasks[0] ? `<span class="agent-line"><span>Working on</span> ${esc(a.tasks[0])}</span>` : "";
    const files = a.files.length ? `<span class="agent-line"><span>Editing</span> ${esc(a.files.slice(0, 2).join(", "))}</span>` : "";
    return `<button type="button" class="row-btn agent-item ${state.selected === key ? "selected" : ""}" data-key="${esc(key)}">
      <span class="agent-id">${avatar(a.agent_id)}<span class="desig">${esc(state.desig.get(key) || "")}</span></span>
      <span style="min-width:0">
        <span class="agent-top"><span class="agent-name">${esc(userOf(a.agent_id))}</span>
          <span class="live-word ${live ? "on" : ""}"><span class="pulse"></span>${live ? "Live" : "Idle"}</span></span>
        <span class="muted ell" style="display:block">${esc(c.name)}${a.role ? " · " + esc(a.role) : ""}${live ? "" : " · seen " + esc(a.last_seen_ago)}</span>
        ${work}${files}
      </span></button>`;
  }).join("") : `<div class="empty"><b>No agents connected</b>Connect one from your repo, then start a session:<br><code>hivemind install claude-code</code></div>`;
}

function renderQueue() {
  const order = { claimed: 0, handed_off: 1, open: 2, done: 3 };
  const tasks = [...(state.team.tasks || [])].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || b.updated_at - a.updated_at);
  $("#task-count").textContent = tasks.length || "";
  $("#queue").innerHTML = tasks.length ? tasks.map((t) => {
    const owner = t.claimed_by || t.created_by;
    const key = keyOf("Task", t.id);
    return `<button type="button" class="row-btn ticket ${state.selected === key ? "selected" : ""}" data-key="${esc(key)}">
      <span class="ticket-title">${esc(t.title)}</span>
      <span class="ticket-meta"><span class="desig">${esc(state.desig.get(key) || "")}</span><span class="mono muted">${ticketId(t.id)}</span>${badge(t.status)}${owner ? avatar(owner, "xs") : ""}<span class="muted when">${esc(t.updated)}</span></span>
    </button>`;
  }).join("") : `<div class="empty"><b>Queue is empty</b>Agents create and claim tasks with the <code>create_task</code> and <code>claim_task</code> tools.</div>`;
}

/* ================================================================ relationship map */
// Designations are assigned by creation order, so an item keeps its number as the graph grows.
const PREFIX = { Agent: "A", Task: "W", Procedure: "P", Fact: "F", Topic: "T" };
function designate(nodes) {
  const out = new Map();
  for (const [label, p] of Object.entries(PREFIX)) {
    nodes.filter((n) => n.label === label && n.id)
      .sort((a, b) => (a.t || 0) - (b.t || 0) || String(a.id).localeCompare(String(b.id)))
      .forEach((n, i) => out.set(keyOf(label, n.id), `${p}${i + 1}`));
  }
  return out;
}

function buildMap() {
  const { nodes, edges } = state.data;
  const by = (label) => nodes.filter((n) => n.label === label && n.id);
  const links = [];
  const add = (from, to, cls = "") => links.push({ from, to, cls });
  const entTopic = new Map();
  for (const e of edges) if (e.type === "IN_TOPIC") entTopic.set(e.src, e.dst);

  const oldest = (a, b) => (a.t || 0) - (b.t || 0) || String(a.id).localeCompare(String(b.id));
  const agents = by("Agent").sort(oldest);
  const tasks = by("Task").sort((a, b) => (a.status === "done") - (b.status === "done") || (b.t || 0) - (a.t || 0)).slice(0, 12);
  const procs = by("Procedure").filter((p) => p.status !== "retracted");
  const facts = by("Fact").filter((f) => f.status === "active").sort((a, b) => (b.importance || 0) - (a.importance || 0) || (b.t || 0) - (a.t || 0));
  // The 20 most important memories, shown newest first within procedures and facts (like every column).
  const top = new Set([...procs, ...facts].slice(0, 20));
  const newest = (a, b) => (b.t || 0) - (a.t || 0);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const olderOf = (f) => edges.filter((e) => e.type === "SUPERSEDES" && e.src === f.id).map((e) => byId.get(e.dst)).filter(Boolean);
  // Past belief stays visible: a superseded fact sits struck through under the fact that replaced it.
  const knowledge = [...procs.filter((n) => top.has(n)).sort(newest), ...facts.filter((n) => top.has(n)).sort(newest).flatMap((f) => [f, ...olderOf(f)])];
  const topics = by("Topic").sort(oldest);
  const shown = new Set([...agents, ...tasks, ...knowledge, ...topics].map((n) => keyOf(n.label, n.id)));

  // Which older facts did each fact replace? (shown as a revision marker, not a node)
  const replaced = new Map();
  for (const e of edges) if (e.type === "SUPERSEDES") replaced.set(e.src, (replaced.get(e.src) || 0) + 1);

  const topicOf = (label, id, rel) => {
    const out = new Set();
    for (const e of edges) if (e.src_label === label && e.src === id && rel.includes(e.type) && entTopic.has(e.dst)) out.add(entTopic.get(e.dst));
    return out;
  };
  const seenPair = new Set();
  const link = (a, b, cls) => { const k = a + "|" + b; if (!seenPair.has(k) && shown.has(a) && shown.has(b)) { seenPair.add(k); add(a, b, cls); } };
  for (const e of edges) {
    const s = keyOf(e.src_label, e.src), d = keyOf(e.dst_label, e.dst);
    if (e.src_label === "Task" && (e.type === "CLAIMED_BY" || e.type === "CREATED_BY")) link(d, s);
    // Agent -> knowledge skips the Work column, so it is drawn only when focused.
    if ((e.src_label === "Fact" || e.src_label === "Procedure") && e.type === "LEARNED_BY") link(d, s, "skip");
  }
  for (const h of by("Handoff")) {
    const task = edges.find((e) => e.src === h.id && e.type === "OF");
    const from = edges.find((e) => e.src === h.id && e.type === "FROM");
    if (task && from) link(keyOf("Agent", from.dst), keyOf("Task", task.dst), "handoff");
  }
  for (const k of knowledge) for (const t of topicOf(k.label, k.id, ["ABOUT", "FOR"])) link(keyOf(k.label, k.id), keyOf("Topic", t));
  for (const t of tasks) for (const tp of topicOf("Task", t.id, ["TOUCHES"])) link(keyOf("Task", t.id), keyOf("Topic", tp), "skip");

  const topicEntities = new Map();
  const entName = new Map(by("Entity").map((n) => [n.id, n.text]));
  for (const e of edges) if (e.type === "IN_TOPIC") {
    if (!topicEntities.has(e.dst)) topicEntities.set(e.dst, []);
    topicEntities.get(e.dst).push(entName.get(e.src) || e.src);
  }
  const handoffTasks = new Set(edges.filter((e) => e.type === "OF").map((e) => e.dst));
  return { agents, tasks, knowledge, topics, links, replaced, topicEntities, handoffTasks,
           hiddenFacts: Math.max(0, procs.length + facts.length - knowledge.length) };
}

function nodeHtml(n, inner, extraCls = "") {
  const key = keyOf(n.label, n.id);
  const fresh = !state.firstRender && !state.asOf && !state.seen.has(key) ? " fresh" : "";
  return `<button type="button" tabindex="-1" class="node ${extraCls}${fresh}${state.selected === key ? " selected" : ""}" data-key="${esc(key)}" title="${esc(n.text)}">
    <span class="desig">${esc(state.desig.get(key) || "")}</span>${inner}</button>`;
}

function renderMap() {
  const m = buildMap();
  state.mapLinks = m.links;
  state.desig = designate(state.data.nodes);
  $("#n-agents").textContent = m.agents.length || "";
  $("#n-work").textContent = m.tasks.length || "";
  const current = m.knowledge.filter((k) => k.label === "Procedure" || k.status === "active").length;
  $("#n-knowledge").textContent = current ? current + (m.hiddenFacts ? ` of ${current + m.hiddenFacts}` : "") : "";
  $("#n-topics").textContent = m.topics.length || "";

  $("#col-agents").innerHTML = m.agents.map((a) => nodeHtml(a, `${avatar(a.id, "sm")}<span style="min-width:0"><span class="node-text">${esc(userOf(a.id))}</span>
      <span class="node-meta">${esc(client(a.id).name)}</span></span>`, "agent")).join("") || `<div class="col-empty">No agents yet.</div>`;

  $("#col-work").innerHTML = m.tasks.map((t) => nodeHtml(t, `<span style="min-width:0"><span class="node-text">${esc(t.text)}</span>
      <span class="node-meta"><span class="mono">${ticketId(t.id)}</span>${badge(t.status || "open")}${m.handoffTasks.has(t.id) ? `<span class="tag blue plain">Handoff</span>` : ""}</span></span>`)).join("")
    || `<div class="col-empty">No shared tasks yet. Agents create them with <code>create_task</code>.</div>`;

  $("#col-knowledge").innerHTML = m.knowledge.map((k) => {
    const isProc = k.label === "Procedure";
    const revs = m.replaced.get(k.id);
    const old = !isProc && k.status && k.status !== "active";
    const meta = isProc ? `<span class="tag green">Verified how-to</span>` : old ? `<span class="tag struck">Superseded</span>` : revs ? `<span class="tag amber plain">Rev ${revs + 1}</span>` : "";
    return nodeHtml(k, `<span style="min-width:0"><span class="node-text">${esc(k.text)}</span>
      <span class="node-meta"><span>${isProc ? "Procedure" : "Fact"} · ${esc(userOf(k.source_agent || k.created_by || ""))}</span>${meta}</span></span>`, old ? "superseded" : "");
  }).join("") + (m.hiddenFacts ? `<div class="col-empty">${m.hiddenFacts} more in Recall and the graph explorer.</div>` : "")
    || `<div class="col-empty">Nothing learned yet. Facts and procedures appear as agents work.</div>`;

  $("#col-topics").innerHTML = m.topics.map((t) => {
    const ents = m.topicEntities.get(t.id) || [];
    const short = (x) => String(x).split("/").filter(Boolean).pop() || x;
    return nodeHtml(t, `<span style="min-width:0"><span class="node-text">${esc(String(t.text).split(" / ").map(short).join(" · "))}</span>
      <span class="node-meta">${ents.length} entities</span>
      <span class="chips">${ents.slice(0, 5).map((e) => `<span class="chip" title="${esc(e)}">${esc(short(e))}</span>`).join("")}${ents.length > 5 ? `<span class="chip">+${ents.length - 5}</span>` : ""}</span></span>`, "topic");
  }).join("") || `<div class="col-empty">Topics appear after consolidation (PageRank and community detection).</div>`;

  for (const n of [...m.agents, ...m.tasks, ...m.knowledge, ...m.topics]) state.seen.add(keyOf(n.label, n.id));
  state.firstRender = false;
  renderAgents(); renderQueue();
  resetRoving();
  requestAnimationFrame(() => { drawLinks(); applyHighlight(); });
}

// Right-angle connectors: out of the source, down the gutter before the target column, into the target.
function drawLinks() {
  const map = $("#map");
  if (!map.offsetParent || isPhone()) return;
  const base = map.getBoundingClientRect();
  const els = new Map($$(".node", map).map((el) => [el.dataset.key, el]));
  const svg = $("#map-links");
  svg.setAttribute("viewBox", `0 0 ${map.scrollWidth} ${map.scrollHeight}`);
  svg.style.height = map.scrollHeight + "px";
  const gap = parseFloat(getComputedStyle(map).columnGap) || 32;
  const r = 0;
  svg.innerHTML = state.mapLinks.map((l) => {
    const a = els.get(l.from), b = els.get(l.to);
    if (!a || !b) return "";
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const x1 = Math.round(ra.right - base.left), y1 = Math.round(ra.top + ra.height / 2 - base.top);
    const x2 = Math.round(rb.left - base.left), y2 = Math.round(rb.top + rb.height / 2 - base.top);
    const xm = Math.round(x2 - gap / 2);
    const dy = y2 - y1;
    let d;
    if (Math.abs(dy) < 2 * r) d = `M${x1},${y1} H${xm} V${y2} H${x2}`;
    else {
      const s = Math.sign(dy);
      d = `M${x1},${y1} H${xm - r} Q${xm},${y1} ${xm},${y1 + s * r} V${y2 - s * r} Q${xm},${y2} ${xm + r},${y2} H${x2}`;
    }
    const ab = `data-a="${esc(l.from)}" data-b="${esc(l.to)}"`;
    return `<path class="${l.cls}" ${ab} d="${d}"/><rect ${ab} x="${x1}" y="${y1 - 2}" width="4" height="4"/><rect ${ab} x="${x2 - 4}" y="${y2 - 2}" width="4" height="4"/>`;
  }).join("");
  applyHighlight();
}
new ResizeObserver(() => requestAnimationFrame(drawLinks)).observe($("#map"));

function neighbours(key) {
  const set = new Set([key]);
  for (const l of state.mapLinks) { if (l.from === key) set.add(l.to); if (l.to === key) set.add(l.from); }
  // Agents and tasks: also show the topics their knowledge touches.
  if (key.startsWith("Agent:") || key.startsWith("Task:")) {
    for (const k of [...set]) for (const l of state.mapLinks) if (l.from === k && l.to.startsWith("Topic:")) set.add(l.to);
  }
  return set;
}
function applyHighlight(hoverKey) {
  const set = hoverKey ? neighbours(hoverKey) : state.pinned || (state.selected ? neighbours(state.selected) : null);
  const map = $("#map");
  map.classList.toggle("dimmed", !!set);
  $$(".node", map).forEach((el) => el.classList.toggle("hl", !!set && set.has(el.dataset.key)));
  $$("#map-links path, #map-links rect").forEach((p) => p.classList.toggle("hl", !!set && set.has(p.dataset.a) && set.has(p.dataset.b)));
}
// The provenance trail draws itself through the map.
function traceLinks() {
  $$("#map-links path.hl").forEach((p) => {
    const len = Math.ceil(p.getTotalLength());
    p.style.setProperty("--len", len);
    restart(p, "trace");
    p.addEventListener("animationend", () => p.classList.remove("trace"), { once: true });
  });
}
const mapEl = $("#map");
mapEl.addEventListener("mouseover", (e) => { const n = e.target.closest(".node"); if (n) applyHighlight(n.dataset.key); });
mapEl.addEventListener("mouseleave", () => applyHighlight());
mapEl.addEventListener("mouseout", (e) => { if (!e.relatedTarget || !e.relatedTarget.closest?.(".node")) applyHighlight(); });
mapEl.addEventListener("focusin", (e) => { const n = e.target.closest(".node"); if (n) applyHighlight(n.dataset.key); });
mapEl.addEventListener("focusout", (e) => { if (!e.relatedTarget?.closest?.(".node")) applyHighlight(); });
mapEl.addEventListener("click", (e) => {
  const n = e.target.closest(".node");
  if (n) select(n.dataset.key);
  else if (!e.target.closest(".col-empty")) { state.selected = null; state.pinned = null; $$(".selected[data-key]").forEach((x) => x.classList.remove("selected")); applyHighlight(); }
});

// Roving focus: one tab stop into the map, arrow keys move between items and columns.
function resetRoving() {
  const nodes = $$(".node", mapEl);
  if (!nodes.length) return;
  const current = nodes.find((n) => n.dataset.key === state.selected) || nodes[0];
  nodes.forEach((n) => (n.tabIndex = n === current ? 0 : -1));
}
mapEl.addEventListener("keydown", (e) => {
  const n = e.target.closest(".node");
  if (!n || !["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const cols = $$(".col-body", mapEl).map((c) => $$(".node", c)).filter((c) => c.length);
  const ci = cols.findIndex((c) => c.includes(n)); const col = cols[ci]; const i = col.indexOf(n);
  let next = n;
  if (e.key === "ArrowDown") next = col[Math.min(col.length - 1, i + 1)];
  if (e.key === "ArrowUp") next = col[Math.max(0, i - 1)];
  if (e.key === "Home") next = col[0];
  if (e.key === "End") next = col[col.length - 1];
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    const target = cols[ci + (e.key === "ArrowRight" ? 1 : -1)];
    if (target) {
      const y = n.getBoundingClientRect().top;
      next = target.reduce((best, el) => Math.abs(el.getBoundingClientRect().top - y) < Math.abs(best.getBoundingClientRect().top - y) ? el : best, target[0]);
    }
  }
  n.tabIndex = -1; next.tabIndex = 0; next.focus();
  next.scrollIntoView({ block: "nearest", inline: "nearest" });
});

/* ================================================================ task board */
function renderBoard() {
  const cols = [["open", "Open"], ["claimed", "In progress"], ["handed_off", "Handed off"], ["done", "Done"]];
  const handoffByTask = new Map();
  for (const h of state.team.handoffs || []) if (!handoffByTask.has(h.task_id)) handoffByTask.set(h.task_id, h);
  $("#board").innerHTML = cols.map(([status, title]) => {
    const tasks = (state.team.tasks || []).filter((t) => t.status === status);
    return `<section class="lane" aria-label="${title}"><div class="head"><h3>${title}</h3><span class="count">${tasks.length}</span></div>
      ${tasks.map((t) => {
        const owner = t.claimed_by || t.created_by;
        const h = handoffByTask.get(t.id);
        return `<button type="button" class="task" data-key="${esc(keyOf("Task", t.id))}">
          <span class="task-title" style="display:block">${esc(t.title)}</span>
          ${t.description ? `<span class="task-desc" style="display:block">${esc(clip(t.description, 140))}</span>` : ""}
          ${h ? `<span class="handoff-note" style="display:block"><span class="handoff-route">${icon("handoff")}${esc(userOf(h.from_agent))} to ${esc(h.to)}</span>${esc(clip(h.summary, 150))}</span>` : ""}
          <span class="task-foot"><span class="desig">${ticketId(t.id)}</span>${owner ? avatar(owner, "xs") + `<span>${esc(userOf(owner))}</span>` : ""}<span class="when">${esc(t.updated)}</span></span>
        </button>`;
      }).join("") || `<div class="lane-empty">None</div>`}</section>`;
  }).join("");
}

/* ================================================================ views and panes */
function setView(v) {
  const changed = state.view !== v;
  state.view = v;
  viewTabs.activate((t) => t.dataset.view === v);
  for (const name of ["map", "board", "graph"]) {
    const el = $(`#view-${name}`);
    el.hidden = name !== v;
    if (name === v && changed) restart(el, "entering");
  }
  document.body.dataset.pane = v;
  syncMobileNav();
  if (v === "map") requestAnimationFrame(drawLinks);
  if (v === "graph") { ensureExplorer(); explorer?.resize(); explorer?.load(state.data); }
}
function setPane(p) {
  if (p === "inspector") { openInspector(); return; }
  closeInspector();
  if (p === "team") { document.body.dataset.pane = "team"; syncMobileNav(); return; }
  setView(p);
}
function syncMobileNav() {
  const pane = document.body.dataset.pane;
  $$(".mobile-nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.pane === (document.body.classList.contains("insp-open") ? "inspector" : pane)));
}
$$(".mobile-nav button").forEach((b) => b.addEventListener("click", () => setPane(b.dataset.pane)));

let lastFocus = null;
function openInspector(focusTitle) {
  if (!isDrawer()) return;
  if (!document.body.classList.contains("insp-open")) lastFocus = document.activeElement;
  document.body.classList.add("insp-open");
  $("#insp-toggle").setAttribute("aria-expanded", "true");
  $("#insp-dot").hidden = true;
  syncMobileNav();
  requestAnimationFrame(() => { inspTabs.move(); (focusTitle && $("#details .detail-title")) ? $("#details .detail-title").focus({ preventScroll: true }) : $("#insp-close").focus({ preventScroll: true }); });
}
function closeInspector() {
  if (!document.body.classList.contains("insp-open")) return;
  document.body.classList.remove("insp-open");
  $("#insp-toggle").setAttribute("aria-expanded", "false");
  syncMobileNav();
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
}
$("#insp-toggle").addEventListener("click", () => (document.body.classList.contains("insp-open") ? closeInspector() : openInspector()));
$("#insp-close").addEventListener("click", closeInspector);
$("#scrim").addEventListener("click", closeInspector);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if ($("#steps-pop").open) { $("#steps-pop").open = false; return; }
    closeInspector();
  }
  if (e.key === "/" && !e.target.closest("input, textarea, select")) { e.preventDefault(); tab("recall"); openInspector(); $("#recall-q").focus(); }
});
mq("(max-width: 1199px)").addEventListener("change", (e) => { if (!e.matches) closeInspector(); inspTabs.move(); });
mq("(max-width: 759px)").addEventListener("change", (e) => {
  if (!e.matches && document.body.dataset.pane === "team") document.body.dataset.pane = state.view;
  requestAnimationFrame(drawLinks);
});

/* ================================================================ graph explorer (raw graph) */

function ensureExplorer() {
  if (explorer) return;
  const el = $("#graph");
  if (typeof ForceGraph === "undefined") {
    el.innerHTML = `<div class="graph-empty">The graph library couldn't load. Check your connection and reload.</div>`;
    return;
  }
  const g = ForceGraph()(el)
    .backgroundColor("rgba(0,0,0,0)")
    .nodeId("key").nodeRelSize(1)
    .nodeVal((n) => n.r * n.r)
    .nodeLabel((n) => `<div style="max-width:300px;font:13px Archivo,sans-serif;padding:6px 8px;background:${cssVar("--sheet")};color:${cssVar("--ink")};border:1px solid ${cssVar("--ink")}"><b>${esc(state.desig.get(n.key) || n.label)}</b> ${esc(n.label)}<br>${esc(clip(n.text, 200))}</div>`)
    .nodeCanvasObject((n, ctx, scale) => {
      const dim = explorer.focus && !explorer.focus.has(n.key);
      ctx.globalAlpha = dim ? 0.15 : 1;
      const square = n.label === "Agent" || n.label === "Task";
      ctx.beginPath();
      if (square) ctx.rect(n.x - n.r, n.y - n.r, n.r * 2, n.r * 2); else ctx.arc(n.x, n.y, n.r, 0, 2 * Math.PI);
      const superseded = n.label === "Fact" && n.status && n.status !== "active";
      ctx.fillStyle = superseded ? cssVar("--sheet") : n.color; ctx.fill();
      if (superseded) { ctx.strokeStyle = n.color; ctx.lineWidth = 1 / scale; ctx.stroke(); }
      if (state.selected === n.key) { ctx.strokeStyle = cssVar("--signal"); ctx.lineWidth = 2.5 / scale; ctx.stroke(); }
      if (["Agent", "Topic"].includes(n.label) || scale > 5 || state.selected === n.key) {
        ctx.font = `500 ${Math.max(11 / scale, 1.5)}px Archivo, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
        ctx.fillStyle = cssVar("--ink-2");
        ctx.fillText(clip(n.label === "Agent" ? n.id : n.text, 36), n.x, n.y + n.r + 2 / scale);
      }
      ctx.globalAlpha = 1;
    })
    .nodePointerAreaPaint((n, color, ctx) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 2, 0, 2 * Math.PI); ctx.fill(); })
    .linkColor(() => cssVar("--link"))
    .linkWidth(0.8)
    .onNodeClick((n) => select(n.key))
    .onBackgroundClick(() => { explorer.focus = null; })
    .cooldownTicks(150);
  g.d3Force("charge").strength(-45);
  const resize = () => { if (el.clientWidth) g.width(el.clientWidth).height(el.clientHeight); };
  new ResizeObserver(resize).observe(el);
  const radius = { Agent: 5, Topic: 5, Task: 4, Procedure: 4.5, Handoff: 3.5, Fact: 3.5, Episode: 2.2, Entity: 2.5, Session: 2, User: 3.5 };
  const colorOf = (n) => (n.label === "Agent" ? client(n.id).color : n.label === "Episode" && n.kind === "error" ? cssVar("--t-error") : typeColor(n.label));
  explorer = {
    g, focus: null, nodes: new Map(), fitted: false, resize,
    load(data) {
      const keep = new Map();
      for (const raw of data.nodes) {
        if (!raw.id || state.hiddenTypes.has(raw.label)) continue;
        const key = keyOf(raw.label, raw.id);
        const n = Object.assign(this.nodes.get(key) || { key }, raw, { key });
        n.r = radius[raw.label] || 3;
        n.color = colorOf(n);
        keep.set(key, n);
      }
      this.nodes = keep;
      const links = data.edges.map((e) => ({ source: keyOf(e.src_label, e.src), target: keyOf(e.dst_label, e.dst) }))
        .filter((l) => keep.has(l.source) && keep.has(l.target));
      g.graphData({ nodes: [...keep.values()], links });
      if (!this.fitted && keep.size) { this.fitted = true; setTimeout(() => g.zoomToFit(600, 80), 1600); }
    },
    refresh() { for (const n of this.nodes.values()) n.color = colorOf(n); g.linkColor(g.linkColor()); renderLegend(); },
  };
  renderLegend();
}
function renderLegend() {
  $("#legend").innerHTML = `<div class="legend-title">Node types</div>` + Object.keys(TYPE_VAR).map((t) =>
    `<button type="button" aria-pressed="${!state.hiddenTypes.has(t)}" data-type="${t}"><i style="background:${typeColor(t)}"></i>${t}</button>`).join("");
}
$("#legend").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-type]"); if (!b) return;
  const t = b.dataset.type; state.hiddenTypes.has(t) ? state.hiddenTypes.delete(t) : state.hiddenTypes.add(t);
  renderLegend(); explorer && explorer.load(state.data);
  $(`#legend button[data-type="${t}"]`)?.focus();
});

/* ================================================================ time travel */
function setRulerStart() {
  $("#tt-start").textContent = state.range.min ? new Date(state.range.min).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) : "";
}
function setTimebar(past) {
  const bar = $("#timebar");
  bar.classList.toggle("live", !past); bar.classList.toggle("past", !!past);
  $("#asof").textContent = past ? "As of " + fmtTime(state.asOf) : "Live";
  $("#slider").setAttribute("aria-valuetext", $("#asof").textContent);
  $("#live-btn").hidden = !past;
}
function setLive() {
  state.asOf = null; $("#slider").value = 1000; setTimebar(false);
  loadGraph();
}
let slideTimer;
$("#slider").addEventListener("input", (e) => {
  const v = +e.target.value;
  if (v >= 1000 || !state.range.min) return setLive();
  state.asOf = Math.round(state.range.min + (state.range.max - state.range.min) * (v / 1000));
  setTimebar(true);
  clearTimeout(slideTimer); slideTimer = setTimeout(loadGraph, 120);
});
$("#live-btn").addEventListener("click", setLive);

/* ================================================================ inspector */
function tab(name) {
  inspTabs.activate((t) => t.dataset.tab === name);
  $$("#inspector .panel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  if (name === "bench") loadBench();
}

const FIELDS = [
  ["status", "Status"], ["kind", "Kind"], ["type", "Type"], ["confidence", "Confidence"], ["key", "Key"],
  ["success_count", "Worked"], ["fail_count", "Failed"], ["uses", "Recalled"], ["importance", "Importance"],
  ["centrality", "Centrality"], ["source_agent", "Learned by"], ["agent_id", "Agent"], ["created_by", "Created by"],
  ["claimed_by", "Held by"], ["from_agent", "From"], ["to_agent", "To agent"], ["to_role", "To role"],
  ["accepted_by", "Accepted by"], ["client", "Client"], ["role", "Role"], ["scope", "Scope"],
  ["promoted_from", "Promoted from"], ["valid_from", "True since"], ["valid_to", "True until"],
  ["recorded_at", "Recorded"], ["ts", "Time"], ["created_at", "Created"], ["started_at", "Started"], ["last_seen", "Last seen"],
];
function fmtField(k, v) {
  if (k === "status") return badge(v);
  if (k === "confidence") return `${Math.round(v * 100)}%`;
  if (["importance", "centrality"].includes(k)) return (+v).toFixed(3);
  if (/(_at|_from|_to|^ts$|last_seen)$/.test(k)) return `${esc(ago(v))} <span class="sub">· ${esc(fmtTime(v))}</span>`;
  return esc(v);
}

let selectSeq = 0;
async function select(key) {
  state.selected = key; state.pinned = null;
  $$("[data-key]").forEach((el) => el.classList.toggle("selected", el.dataset.key === key));
  applyHighlight();
  resetRoving();
  tab("details");
  if (isDrawer()) openInspector(false);
  const seq = ++selectSeq;
  const [label, ...rest] = key.split(":"); const id = rest.join(":");
  $("#details").className = "";
  $("#details").innerHTML = `<div class="skel" style="height:30px;border:0"></div><div class="skel"></div><div class="skel"></div>`;
  const d = await api(`/api/node?workspace=${state.ws}&id=${encodeURIComponent(id)}`).catch(() => null);
  if (seq !== selectSeq) return;
  if (!d) { $("#details").innerHTML = `<div class="notice error">Couldn't load this item. It may have been removed, or the server is unreachable.</div>`; return; }
  const title = d.statement || d.goal || d.text || d.title || d.summary || d.name || d.label || id;
  const by = d.source_agent || d.created_by || d.agent_id || d.from_agent;
  const when = d.recorded_at || d.ts || d.created_at || d.started_at;
  const desig = state.desig.get(key);
  const props = FIELDS.filter(([k]) => d[k] !== undefined && d[k] !== null && d[k] !== "")
    .map(([k, name]) => `<dt>${name}</dt><dd>${fmtField(k, d[k])}</dd>`).join("");
  const steps = Array.isArray(d.steps) ? `<section class="section"><div class="head"><h4>Steps</h4><span class="count">${d.steps.length}</span></div><ol class="steps">${d.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></section>` : "";
  const next = Array.isArray(d.next_steps) && d.next_steps.length ? `<section class="section"><div class="head"><h4>Next steps</h4></div><ul class="plain-list">${d.next_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></section>` : "";
  const canWhy = ["Fact", "Procedure", "Episode"].includes(label);
  $("#details").innerHTML = `
    <h3 class="detail-title" tabindex="-1">${esc(title)}</h3>
    <div class="detail-sub"><span class="type-tag">${desig ? `<span class="desig">${esc(desig)}</span>` : ""}${esc(label === "Task" ? "Task " + ticketId(id) : label)}</span>${by ? "<span>by " + esc(by) + "</span>" : ""}${when ? "<span>" + esc(ago(when)) + "</span>" : ""}</div>
    ${canWhy || label === "Entity" ? `<div class="detail-actions">
      ${canWhy ? `<button class="btn primary small" id="why-btn" type="button">Why do we know this?</button>` : ""}
      ${label === "Entity" ? `<button class="btn small" id="tl-btn" type="button">Knowledge timeline</button>` : ""}</div>` : ""}
    <div id="why-out"></div>
    ${steps}${next}
    ${props ? `<section class="section"><div class="head"><h4>Specification</h4></div><dl class="kv">${props}</dl></section>` : ""}
    <section class="section"><div class="head"><h4>Identifier</h4></div><code class="ident">${esc(id)}</code></section>`;
  if (canWhy) $("#why-btn").onclick = () => why(id);
  if (label === "Entity") $("#tl-btn").onclick = () => timeline(d.name || id);
}

async function why(id) {
  const btn = $("#why-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Tracing…"; }
  const w = await api(`/api/why?workspace=${state.ws}&id=${encodeURIComponent(id)}`).catch(() => ({ error: "Couldn't trace this memory right now. Try again in a moment." }));
  if (btn) { btn.disabled = false; btn.textContent = "Why do we know this?"; }
  if (w.error) { $("#why-out").innerHTML = `<div class="notice error" style="margin-top:16px">${esc(w.error)}</div>`; return; }
  const keys = new Set(w.graph.nodes.map((n) => keyOf(n.label, n.id)));
  keys.add(keyOf(w.label, id));
  // Agents behind the provenance, plus topics of the entities it is about.
  for (const n of w.graph.nodes) if (n.label === "Entity") {
    const t = state.data.edges.find((e) => e.type === "IN_TOPIC" && e.src === n.id);
    if (t) keys.add(keyOf("Topic", t.dst));
  }
  state.pinned = keys; applyHighlight(); traceLinks();
  if (explorer) explorer.focus = keys;
  // Cross-reference: every map item the trail passes through, by designation.
  const onMap = $$(".node", mapEl).filter((el) => keys.has(el.dataset.key) && el.dataset.key !== state.selected);
  const xref = onMap.length ? `<div class="xref" aria-label="Map items in this trail">${onMap.map((el) =>
    `<button type="button" data-key="${esc(el.dataset.key)}"><span class="desig">${esc(state.desig.get(el.dataset.key) || "")}</span><span>${esc(el.title)}</span></button>`).join("")}</div>` : "";
  $("#why-out").innerHTML = `<section class="section"><div class="head"><h4>Provenance</h4><span class="count">${w.explanation.length} steps</span></div>
    <ol class="trail">${w.explanation.map((l, i) => `<li style="--i:${i}">${esc(l)}</li>`).join("")}</ol>${xref}</section>`;
}

async function timeline(entity) {
  const rows = await api(`/api/timeline?workspace=${state.ws}&entity=${encodeURIComponent(entity)}`).catch(() => null);
  if (!rows) { $("#why-out").innerHTML = `<div class="notice error" style="margin-top:16px">Couldn't load the timeline.</div>`; return; }
  $("#why-out").innerHTML = `<section class="section"><div class="head"><h4>How our knowledge changed</h4></div>` + (rows.length ? `<ol class="trail">${rows.map((r, i) =>
    `<li style="--i:${i}">${badge(r.status)} ${esc(r.statement)}<div class="feed-time">Learned ${esc(r.learned)} by ${esc(r.source_agent)}${r.ended ? " · replaced " + esc(r.ended) : ""}</div></li>`).join("")}</ol>`
    : `<div class="notice">No facts about this yet.</div>`) + `</section>`;
}

document.addEventListener("click", (e) => {
  const el = e.target.closest(".agent-item, .ticket, .task, .result[data-key], .xref button[data-key]");
  if (el) select(el.dataset.key);
});

/* ================================================================ recall */
async function recall(q) {
  const p = new URLSearchParams({ workspace: state.ws, q }); if (state.asOf) p.set("as_of", state.asOf);
  const out = $("#recall-results");
  out.setAttribute("aria-busy", "true");
  out.innerHTML = `<p class="hint" style="margin-top:0">Searching vectors, keywords and graph neighbours…</p><div class="skel tall"></div><div class="skel tall"></div>`;
  const r = await api(`/api/recall?${p}`).catch(() => null);
  out.removeAttribute("aria-busy");
  if (!r) { out.innerHTML = `<div class="notice error">Recall failed. Check that the server can reach FalkorDB, then try again.</div>`; return; }
  if (!r.results.length) {
    out.innerHTML = `<div class="notice"><b>Not in the graph.</b> Nothing in team memory matches this, and Hivemind says so instead of guessing.</div>`;
    return;
  }
  const L = { fact: "Fact", procedure: "Procedure", episode: "Episode" };
  const cls = { fact: "blue", procedure: "green", episode: "plain" };
  out.innerHTML = (state.asOf ? `<div class="notice past">Answering as of ${esc(fmtTime(state.asOf))}</div>` : "") +
    r.results.map((x, i) => {
      const w = x.why_ranked; const prov = x.provenance || {};
      return `<button type="button" class="result" data-key="${esc(keyOf(L[x.type], x.id))}" style="--i:${i}">
        <span class="result-head"><span class="tag ${cls[x.type]}">${esc(L[x.type])}</span>
          <span class="score" title="Relevance">${x.score.toFixed(2)}<span class="score-bar"><i style="width:${Math.min(100, x.score * 100)}%"></i></span></span></span>
        <span class="result-text" style="display:block">${esc(x.text)}</span>
        ${x.steps ? `<ol class="steps">${x.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>` : ""}
        <span class="signals"><span>Semantic <b>${w.semantic.toFixed(2)}</b></span>${w.keyword ? `<span>Keyword <b>${w.keyword.toFixed(2)}</b></span>` : ""}${w.graph_hops !== null ? `<span>Graph <b>${w.graph_hops} hop${w.graph_hops === 1 ? "" : "s"}</b></span>` : ""}${x.success_rate !== undefined ? `<span>Worked <b>${Math.round(x.success_rate * 100)}%</b></span>` : ""}</span>
        ${prov.learned_by ? `<span class="result-foot" style="display:block">Learned by ${esc(prov.learned_by.join(", "))}${prov.about && prov.about.length ? " · about " + esc(prov.about.slice(0, 3).join(", ")) : ""}</span>` : ""}
      </button>`;
    }).join("");
}
$("#recall-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#recall-q").value.trim(); if (q) recall(q);
});
$("#suggest").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  $("#recall-q").value = b.textContent; recall(b.textContent);
});

/* ================================================================ activity, toasts, narration */
function describe(e) {
  const who = `<b>${esc(userOf(e.agent))}</b>`;
  const t = esc(clip(e.text || "", 180));
  switch (e.type) {
    case "episode.added": return ["Episode", e.kind === "error" ? `${who}'s command failed: ${t}` : `${who} · ${esc(e.kind)}: ${t}`, e.kind === "error" ? "--t-error" : null];
    case "fact.learned": return ["Fact", `${who} learned: ${t}`];
    case "fact.reinforced": return ["Fact", `${who} confirmed: ${t}`];
    case "fact.superseded": return ["Fact", `Replaced, kept as history: ${t}`, "--amber"];
    case "fact.promoted": return ["User", `${who} shared a private note with the team: ${t}`];
    case "procedure.learned": return ["Procedure", e.auto ? `Learned automatically from ${who}'s session: ${t}` : `${who} recorded a procedure: ${t}`];
    case "procedure.outcome": return ["Procedure", `${who} reported a procedure ${e.ok ? "worked" : "failed"}`];
    case "task.created": return ["Task", `${who} created task: ${t}`];
    case "task.claimed": return ["Task", `${who} claimed: ${t}`];
    case "task.completed": return ["Task", `${who} completed: ${t}`];
    case "handoff.created": return ["Handoff", `${who} handed off to ${esc(e.to)}: ${t}`];
    case "handoff.accepted": return ["Handoff", `${who} accepted a handoff`];
    case "conflict.warned": return ["Episode", `Collision avoided: ${who} was warned that ${esc(e.other)} is editing ${esc(e.file)}`, "--signal"];
    case "assist": return ["Episode", `Known fix served to ${who} for failing <code>${esc(e.command)}</code>`, "--signal"];
    case "session.started": return ["Session", `${who} started a ${esc(client(e.agent).name)} session`];
    case "memory.consolidated": return ["Topic", `Consolidated memory into ${e.topics} topics (PageRank and communities)`];
    case "demo.step": return ["Agent", esc(e.text), "--signal"];
    default: return null;
  }
}
function feedItem(label, html, ts, colorVar, fresh) {
  const div = document.createElement("div");
  div.className = "feed-item" + (fresh ? " fresh" : "");
  const c = colorVar ? cssVar(colorVar) : typeColor(label);
  div.innerHTML = `<i style="background:${c}" aria-hidden="true"></i><div class="feed-text">${html}</div><span class="feed-time">${ts ? esc(ago(ts)) : ""}</span>`;
  return div;
}
async function loadFeed() {
  const rows = await api(`/api/feed?workspace=${state.ws}&limit=80`);
  const f = $("#feed"); f.innerHTML = "";
  for (const r of rows) {
    const who = r.agent ? `<b>${esc(userOf(r.agent))}</b> · ` : "";
    const txt = esc(clip(r.text || "", 180));
    const html = r.label === "Episode" ? `${who}${esc(r.kind)}: ${txt}` : r.label === "Fact" ? `${who}learned: ${txt}` : `${who}${esc(r.label.toLowerCase())}: ${txt}`;
    f.append(feedItem(r.label, html, r.ts, r.kind === "error" ? "--t-error" : null, false));
  }
  if (!rows.length) f.innerHTML = `<div class="placeholder"><b class="title">No activity yet</b>Press <b>Play the demo</b> to watch three agents share one memory.</div>`;
}
const TOAST_ICON = { success: "check", warning: "bolt", danger: "alert", "": "info" };
function toast(kind, title, body) {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.setAttribute("role", kind === "danger" ? "alert" : "status");
  t.innerHTML = `${icon(TOAST_ICON[kind] || "info")}<div><b>${esc(title)}</b>${esc(clip(body, 200))}</div>`;
  const box = $("#toasts");
  box.append(t);
  const remove = () => { t.classList.add("out"); t.addEventListener("animationend", () => t.remove(), { once: true }); };
  setTimeout(remove, 6500);
  t.addEventListener("click", remove);
  while (box.children.length > 3) box.firstChild.remove();
}

// The demo narrates itself: a numbered band, one tick per step, and the story so far.
function narrate(text, done = false) {
  const band = $("#narration");
  band.hidden = false;
  band.classList.toggle("done", done);
  if (!done) {
    state.steps.push(text);
    const ti = document.createElement("i"); $("#ticks").append(ti);
    $("#steps-list").insertAdjacentHTML("beforeend", `<li><span>${String(state.steps.length).padStart(2, "0")}</span>${esc(text)}</li>`);
  }
  if (done) $("#step-no").innerHTML = icon("check");
  else $("#step-no").textContent = String(state.steps.length).padStart(2, "0");
  $("#steps-count").textContent = state.steps.length;
  $("#steps-pop").hidden = !state.steps.length;
  const tx = $("#narr-text"); tx.textContent = text; restart(tx, "swap");
  $("#narr-close").hidden = !done;
  requestAnimationFrame(drawLinks);
}
function resetNarration() {
  state.steps = [];
  $("#ticks").innerHTML = ""; $("#steps-list").innerHTML = "";
  $("#steps-pop").open = false;
}
$("#narr-close").addEventListener("click", () => { $("#narration").hidden = true; requestAnimationFrame(drawLinks); });

function onEvent(e) {
  if (e.workspace !== state.ws) return;
  // These episodes duplicate a richer event (assist, fact.learned) shown separately.
  const d = e.type === "episode.added" && ["assist", "learning", "handoff"].includes(e.kind) ? null : describe(e);
  if (d && e.type !== "demo.step") {
    if ($("#feed .placeholder, #feed .skel")) $("#feed").innerHTML = "";
    $("#feed").prepend(feedItem(d[0], d[1], e.ts, d[2], true));
    while ($("#feed").children.length > 200) $("#feed").lastChild.remove();
    if (isPhone() && !document.body.classList.contains("insp-open")) $("#insp-dot").hidden = false;
  }
  switch (e.type) {
    case "assist": toast("warning", "Known fix served", `${userOf(e.agent)} hit a failure the team has seen before and got the verified fix instantly.`); break;
    case "procedure.learned": if (e.auto) toast("success", "Procedure learned automatically", `${e.text}: ${(e.steps || []).join(" → ")}`); break;
    case "conflict.warned": toast("danger", "Collision avoided", `${userOf(e.agent)} was about to edit ${e.file}, which ${e.other} is editing.`); break;
    case "fact.superseded": toast("", "Knowledge updated", `Older belief kept as history: “${e.text}”`); break;
    case "demo.step": narrate(e.text); break;
    case "demo.finished":
      narrate("Demo complete. Select any memory and press Why do we know this?, or drag Time travel to see last week.", true);
      setPlaying(false); loadWorkspaces(); break;
  }
  if (e.type !== "demo.step") scheduleRefresh();
}

let es;
function connectEvents() {
  if (es) es.close();
  es = new EventSource(`/api/events?workspace=${encodeURIComponent(state.ws)}`);
  const chip = $("#live");
  es.addEventListener("memory", (m) => onEvent(JSON.parse(m.data)));
  es.onopen = () => { chip.classList.add("on"); $(".status-text", chip).textContent = "Live"; };
  es.onerror = () => { chip.classList.remove("on"); $(".status-text", chip).textContent = "Reconnecting"; };
}

/* ================================================================ benchmarks */
async function loadBench() {
  const b = await api("/api/bench").catch(() => ({}));
  if (!Object.keys(b).length) return;
  const el = $("#bench"); el.className = "";
  let html = "";
  // One block per A/B scenario file (ab_memory_only.json first, then ab_in_repo.json).
  for (const key of Object.keys(b).filter((k) => k.startsWith("ab")).sort().reverse()) {
    const a = b[key]; const [off, on] = a.runs;
    // Averages over a few runs: one decimal, and no "win" marker; the note carries the interpretation.
    const fmt = (r, k) => (k === "correct" ? `${r.correct}/${r.runs}` : (+r[k]).toFixed(k === "cost_usd" ? 3 : 1));
    html += `<section class="bench-block"><div class="head"><h4>Claude Code with and without Hivemind: ${esc(a.title || "same task")}</h4></div><p>${esc(a.description || "")}</p>
      <table class="compare"><thead><tr><th scope="col">Measure</th><th scope="col" class="num">Without</th><th scope="col" class="num">With Hivemind</th></tr></thead><tbody>
      ${(a.metrics || ["turns", "duration_s"]).map((k) => `<tr><td>${esc(a.labels?.[k] || k)}</td><td class="num">${fmt(off, k)}</td><td class="num on">${fmt(on, k)}</td></tr>`).join("")}
      </tbody></table>
      ${a.note ? `<p style="margin:10px 0 0">${esc(a.note)}</p>` : ""}</section>`;
  }
  if (b.concurrency) {
    const c = b.concurrency;
    const max = Math.max(...c.scenarios.map((s) => s.ops_per_s));
    html += `<section class="bench-block"><div class="head"><h4>Concurrent agents on one FalkorDB instance</h4><span class="count">ops/s</span></div><p>${esc(c.description || "Mixed reads and writes; higher is better.")}</p>
      <div class="bars">${c.scenarios.map((s) => `<div class="bar-row"><span class="label" title="${esc(s.name)}">${esc(s.name)}</span>
        <span class="value">${Math.round(s.ops_per_s).toLocaleString()}</span><span class="bar-track"><i style="width:${(s.ops_per_s / max) * 100}%"></i></span></div>`).join("")}</div>
      <dl class="kv" style="margin-top:14px">${c.scenarios.map((s) => `<dt>${esc(s.name)}</dt><dd>p50 ${s.p50_ms.toFixed(1)} ms · p95 ${s.p95_ms.toFixed(1)} ms</dd>`).join("")}</dl></section>`;
    if (c.race) html += `<section class="bench-block"><div class="head"><h4>Claim race</h4></div><div class="big-pair">
      <div><div class="v">${c.race.agents}</div><div class="k">Agents racing per trial</div></div>
      <div><div class="v">${c.race.exactly_one_winner}/${c.race.trials}</div><div class="k">Trials with exactly one winner</div></div></div></section>`;
    if (c.machine) html += `<p class="machine">${esc(c.machine)} · ${esc(c.generated_at || "")}</p>`;
  }
  el.innerHTML = html;
}

/* ================================================================ workspace, demo, consolidate */
async function loadWorkspaces() {
  const list = await api("/api/workspaces").catch(() => []);
  const names = list.map((w) => w.workspace);
  if (!names.includes(state.ws)) names.unshift(state.ws);
  $("#workspace").innerHTML = names.map((n) => `<option ${n === state.ws ? "selected" : ""}>${esc(n)}</option>`).join("");
}
function switchWorkspace(ws) {
  Object.assign(state, { ws, asOf: null, selected: null, pinned: null, seen: new Set(), firstRender: true, stats: null });
  history.replaceState(null, "", `?workspace=${encodeURIComponent(ws)}`);
  $("#slider").value = 1000; setTimebar(false);
  if (explorer) explorer.fitted = false;
  connectEvents(); refreshAll();
}
$("#workspace").addEventListener("change", (e) => switchWorkspace(e.target.value));

function setPlaying(on) {
  $("#play").disabled = on;
  $("#play .btn-label").textContent = on ? "Playing…" : "Play the demo";
  $("#play .btn-label-short").textContent = on ? "Playing" : "Play";
  $("#play").setAttribute("aria-label", on ? "Demo playing" : "Play the demo");
}
$("#play").addEventListener("click", async () => {
  setPlaying(true);
  if (state.ws !== "demo") switchWorkspace("demo");
  Object.assign(state, { seen: new Set(), firstRender: false, selected: null, pinned: null });
  state.data = { nodes: [], edges: [] }; renderMap();
  $("#feed").innerHTML = "";
  resetNarration();
  tab("activity"); setPane("map");
  narrate("Starting: three AI agents (Claude Code, Cursor, Codex) share one Hivemind…");
  const r = await fetch(`/api/demo/play?workspace=demo`, { method: "POST" }).catch(() => null);
  if (r && r.status === 409) narrate("A demo is already playing. Watch along.");
  else if (!r || !r.ok) { setPlaying(false); narrate("The demo couldn't start. Check that the server can reach FalkorDB, then press Play again.", true); }
});
$("#consolidate").addEventListener("click", async () => {
  const b = $("#consolidate");
  b.disabled = true;
  const r = await api(`/api/consolidate?workspace=${state.ws}`, { method: "POST" }).catch(() => null);
  b.disabled = false;
  if (r) toast("success", "Memory consolidated", `PageRank ranked ${r.entities_ranked} entities and found ${r.topics.length} topics.`);
  else toast("danger", "Consolidation failed", "The server couldn't run PageRank right now. Try again in a moment.");
  scheduleRefresh(50);
});

async function refreshAll() {
  await loadRange();
  await Promise.allSettled([loadGraph(), loadTeam(), loadStats(), loadFeed()]);
}

window.addEventListener("resize", () => requestAnimationFrame(drawLinks));
document.fonts?.ready.then(() => { requestAnimationFrame(drawLinks); viewTabs.move(); inspTabs.move(); });
viewTabs.activate((t) => t.dataset.view === "map");
inspTabs.activate((t) => t.dataset.tab === "details");
loadWorkspaces();
connectEvents();
refreshAll();
api("/api/demo/status").then((s) => { if (s.playing) setPlaying(true); }).catch(() => {});
