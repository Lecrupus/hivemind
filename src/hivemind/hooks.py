"""Claude Code hook handlers: memory that works without the agent asking.

  SessionStart       -> register the session, inject the team briefing
  UserPromptSubmit   -> store the prompt (conversation history), inject relevant memory
  PreToolUse (edits) -> warn if another live agent is editing the same file
  PostToolUse        -> track edited files; learn procedures from fail -> fix -> success
  PostToolUseFailure -> store the error, inject the team's known fix if there is one
  Stop               -> store the agent's reply (conversation history)
  SessionEnd         -> close the session

Procedure mining: when a command fails, the session remembers it. Commands
that change state afterwards are collected. When the same command later
succeeds, those steps become an auto-learned Procedure that every agent sees.
"""

from __future__ import annotations

import time

from . import queries as Q
from .core import Actor, Hivemind
from .text import clip, command_key, error_signature, is_inspect_only, now_ms

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
FAIL_WINDOW_MS = 30 * 60_000
MAX_STEPS = 8

_warned: dict[tuple[str, str], float] = {}  # (session, file) -> last conflict warning time


def handle(hm: Hivemind, event: str, payload: dict, actor: Actor) -> dict:
    actor.session_id = payload.get("session_id") or actor.session_id
    actor.cwd = payload.get("cwd") or actor.cwd
    actor.branch = payload.get("_branch") or actor.branch
    fn = HANDLERS.get(event)
    if fn is None:
        return {}
    return fn(hm, payload, actor) or {}


def _context(event: str, text: str, **extra) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}, **extra}


# ---------------------------------------------------------------- session


def session_start(hm: Hivemind, p: dict, a: Actor) -> dict:
    hm.start_session(a, a.session_id)
    b = hm.briefing(a)
    c = b["counts"]
    bits = [f"{c.get('Fact', 0)} facts", f"{c.get('Procedure', 0)} procedures"]
    if b["inbox"]:
        bits.append(f"{len(b['inbox'])} handoff(s) for you")
    if b["team"]:
        bits.append(f"{len(b['team'])} teammate(s) active")
    return _context("SessionStart", b["text"], systemMessage=f"Hivemind connected ({a.workspace}): " + ", ".join(bits))


def session_end(hm: Hivemind, p: dict, a: Actor) -> dict:
    hm.end_session(a, p.get("reason") or "ended")
    return {}


def prompt(hm: Hivemind, p: dict, a: Actor) -> dict:
    text = (p.get("prompt") or "").strip()
    if not text:
        return {}
    hm.remember(a, text, kind="prompt", importance=0.6)
    if len(text) < 12 or text.startswith("/"):
        return {}
    r = hm.recall(a, text, k=5, types=("fact", "procedure"))
    relevant = [i for i in r["results"] if i["score"] >= 0.55]
    if not relevant:
        return {}
    return _context("UserPromptSubmit", "Hivemind team memory relevant to this request:\n"
                    + hm._summarize(relevant))


def stop(hm: Hivemind, p: dict, a: Actor) -> dict:
    if p.get("stop_hook_active"):
        return {}
    msg = (p.get("last_assistant_message") or "").strip()
    if msg:
        hm.remember(a, clip(msg, 1500), kind="response", importance=0.3)
    return {}


# ---------------------------------------------------------------- tools


def pre_tool(hm: Hivemind, p: dict, a: Actor) -> dict:
    if p.get("tool_name") not in EDIT_TOOLS or hm.settings.conflict_mode == "off":
        return {}
    ti = p.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        return {}
    hm.ensure_session(a)
    conflicts = hm.file_conflicts(a, path)
    if not conflicts:
        return {}
    key = (a.session_id or "", conflicts[0]["file"])
    if time.time() - _warned.get(key, 0) < 600:  # warn once per file per 10 minutes
        return {}
    _warned[key] = time.time()
    c = conflicts[0]
    task = f" while working on '{c['tasks'][0]}'" if c["tasks"] else ""
    msg = (f"Hivemind: {c['agent_id']} (another live session) edited {c['file']} {c['when']}{task}. "
           f"Check team_status or coordinate before changing it.")
    hm._publish(a, "conflict.warned", file=c["file"], other=c["agent_id"])
    out = _context("PreToolUse", msg, systemMessage=msg)
    if hm.settings.conflict_mode == "ask":
        out["hookSpecificOutput"].update(permissionDecision="ask", permissionDecisionReason=msg)
    return out


def _fail_state(hm: Hivemind, a: Actor) -> dict:
    rows = hm.db.ro_query(hm.shared(a), Q.SESSION_STATE, {"session_id": a.session_id})
    return rows[0] if rows else {}


def post_tool(hm: Hivemind, p: dict, a: Actor) -> dict:
    tool = p.get("tool_name")
    ti = p.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path")
        if path:
            hm.touch_file(a, path)
        return {}
    if tool != "Bash":
        return {}
    cmd = (ti.get("command") or "").strip()
    if not cmd or is_inspect_only(cmd):
        return {}
    hm.ensure_session(a)
    key = command_key(cmd)
    ep = hm.remember(a, f"$ {clip(cmd, 500)}", kind="action", about=[key] if key else None, importance=0.2)
    st = _fail_state(hm, a)
    if not st.get("fail_key"):
        return {}
    if key == st["fail_key"]:
        hm.db.query(hm.shared(a), Q.CLEAR_FAIL_STATE, {"session_id": a.session_id})
        steps = list(st.get("steps_since_fail") or [])
        if not steps:
            return {}  # it just worked on retry: nothing to teach
        goal = f"Run `{st['fail_key']}` successfully"
        res = hm.record_procedure(a, goal, steps + [cmd], outcome="success", about=[st["fail_key"]], auto=True,
                                  episode_ids=[e for e in (st.get("fail_episode"), ep["id"]) if e])
        verb = "reinforced" if res["status"] == "reinforced" else "learned"
        msg = (f"Hivemind {verb} a procedure from this session for teammates: '{goal}': "
               + " -> ".join(steps + [cmd]) + f" [{res['id']}]")
        return _context("PostToolUse", msg, systemMessage=f"Hivemind {verb} procedure: {goal}")
    steps = (list(st.get("steps_since_fail") or []) + [clip(cmd, 400)])[-MAX_STEPS:]
    hm.db.query(hm.shared(a), Q.SET_FAIL_STATE, {"session_id": a.session_id, "fail_key": st["fail_key"],
                                                  "fail_cmd": st.get("fail_cmd"), "fail_episode": st.get("fail_episode"),
                                                  "steps": steps})
    return {}


def post_tool_failure(hm: Hivemind, p: dict, a: Actor) -> dict:
    if p.get("tool_name") != "Bash" or p.get("is_interrupt"):
        return {}
    cmd = ((p.get("tool_input") or {}).get("command") or "").strip()
    err = str(p.get("error") or "")
    if not cmd:
        return {}
    hm.ensure_session(a)
    key = command_key(cmd)
    sig = error_signature(err)
    ep = hm.remember(a, f"$ {clip(cmd, 400)}\nfailed: {clip(err, 1500)}", kind="error",
                     about=[key] if key else None, importance=0.7)
    st = _fail_state(hm, a)
    # Track the first failure; a fix attempt that itself fails doesn't reset it.
    if key and not is_inspect_only(cmd) and (not st.get("fail_key") or st["fail_key"] == key):
        hm.db.query(hm.shared(a), Q.SET_FAIL_STATE, {
            "session_id": a.session_id, "fail_key": key, "fail_cmd": clip(cmd, 400), "fail_episode": ep["id"],
            "steps": list(st.get("steps_since_fail") or []) if st.get("fail_key") == key else []})
    return known_fix(hm, a, key, cmd, sig, exclude_session=a.session_id)


def known_fix(hm: Hivemind, a: Actor, key: str | None, cmd: str, sig: str, exclude_session: str | None) -> dict:
    """Look up what the team knows about this failure and hand it to the agent right now."""
    lines = []
    # Only confident matches: a procedure for this very command, or a near-identical goal;
    # facts must be about the error itself, not merely mention the same tool.
    procs = [pr for pr in hm.find_procedure(a, f"Run `{key or cmd}` successfully", k=3)
             if (pr["entity_match"] or pr["similarity"] >= 0.82) and pr["success_count"] > pr["fail_count"]][:2]
    for pr in procs:
        lines.append(f"- Procedure [{pr['id']}] '{pr['goal']}' (worked {pr['success_count']}x, failed "
                     f"{pr['fail_count']}x, by {pr['created_by']}): " + " -> ".join(pr["steps"]))
    # Compare facts to the root-cause line only: including the command would make
    # every fact that mentions the same tool look relevant.
    facts = [f for f in hm.recall(a, sig or cmd, k=3, types=("fact",), bump=False)["results"]
             if f["why_ranked"]["semantic"] >= 0.66]
    for f in facts:
        who = ", ".join((f.get("provenance") or {}).get("learned_by") or [])
        lines.append(f"- Fact [{f['id']}] ({who}): {f['text']}")
    seen = [e for e in hm.recall(a, f"$ {cmd}\nfailed: {sig}", k=5, types=("episode",), bump=False)["results"]
            if e.get("kind") == "error" and e["why_ranked"]["semantic"] >= 0.85 and e.get("agent") != a.agent_id]
    if seen:
        agents = sorted({e.get("agent") for e in seen if e.get("agent")})
        lines.append(f"- This error was hit before by {', '.join(agents)} ({seen[0]['when']}).")
    if not (procs or facts):
        return {}
    if procs:
        hm._bump(a, [{"type": "procedure", "id": pr["id"], "scope": pr["scope"]} for pr in procs])
    hm.remember(a, f"Hivemind suggested a known fix for failing `{key or cmd}`: "
                + "; ".join(pr["id"] for pr in procs) + " " + "; ".join(f["id"] for f in facts),
                kind="assist", importance=0.4)
    hm._publish(a, "assist", command=key or cmd, procedures=[pr["id"] for pr in procs], facts=[f["id"] for f in facts])
    text = "Hivemind: your team has seen this failure before.\n" + "\n".join(lines)
    if procs:
        text += f"\nIf you follow a procedure, call report_outcome('{procs[0]['id']}', success) afterwards."
    return _context("PostToolUseFailure", text, systemMessage="Hivemind found a known fix from team memory")


HANDLERS = {
    "session-start": session_start,
    "prompt": prompt,
    "pre-tool": pre_tool,
    "post-tool": post_tool,
    "post-tool-failure": post_tool_failure,
    "stop": stop,
    "session-end": session_end,
}
