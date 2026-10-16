# Demo video script (under 3 minutes)

**Setup before recording:**
- Run `docker compose up -d`, open http://localhost:8765 in a 1440×900 browser window, light theme.
- Keep a terminal ready with Claude Code in `demo/sample-repo`, if you want to show a real agent.
- Record at 1080p. Zoom the browser to 110% so the text is readable.

**Tone:** calm, specific, no hype words. Let the captions and toasts do the work.

---

### 0:00–0:20 · The problem (talking over a terminal or a plain slide)
> "We all run several AI coding agents now. They don't remember anything. One agent spends twenty minutes discovering that the tests need the database container. An hour later another agent rediscovers it from scratch, while a third edits the same file. Hivemind gives them one shared memory, built on FalkorDB."

### 0:20–1:30 · Play the demo (the dashboard)
Click **Play the demo**. Say little; point at each moment:

1. **(~0:30)** Caption: *Alice's agent hits a failing test.* The test **Procedure learned automatically** toast appears.
   > "Nobody told Hivemind anything. It watched fail, fix, success, and saved the steps."
2. **(~0:45)** Toast: *Collision avoided.*
   > "Bob's agent was about to edit the file Alice's agent is editing. It got warned first."
3. **(~0:55)** Toast: *Known fix served.* The metric **Known fixes served** goes to 1.
   > "The CI agent hits the same error, and gets Alice's verified fix at the moment it fails. That's the core idea: a mistake is made once."
4. **(~1:10)** Handoff appears on the task board (switch to **Task board** for 3 seconds).
   > "Alice hands off to whoever is the reviewer, with the decision and the procedure attached."
5. **(~1:20)** Caption: *Exactly one wins.*
   > "Three agents race for one task. One query, and FalkorDB's per-graph write ordering makes it race-free."

### 1:30–2:15 · Why it's a graph
1. Click the **Run `pytest` successfully** procedure, then **Why do we know this?**. The trail lights up from Alice's agent to the procedure to the topic.
   > "Every memory traces back to the session, agent and person it came from."
2. Drag **Time travel** back to "last week". The pnpm fact reappears; drag back to Live and it shows as bun.
   > "Facts are never overwritten. We can ask what the team believed on any date."
3. Open **Recall** and type *how do I run the tests*. Point at the "Semantic / Keyword / Graph · 0 hops" badges.
   > "Recall combines FalkorDB's vector index, full-text search and graph hops, and says why each result ranked."
4. (Optional, 5 seconds) Open the FalkorDB Browser on :3000 and show the graph.

### 2:15–2:45 · Proof
Open **Benchmarks**.
> "With 100 concurrent agents, about 1,300 memory operations a second, several thousand FalkorDB queries a second, with zero errors, and one graph per tenant beats a shared graph. In 20 races of 100 agents, there was exactly one winner every time."

Then show the **"Knowledge only in team memory"** tiles in the Benchmarks tab:
> "And on real Claude Code: when a rule lived only in a teammate's earlier session, Claude got it wrong both times without Hivemind, and right both times with it. It costs a few cents more per run. When the rule was already written in the repo, memory made no difference, and we say so."

### 2:45–3:00 · Close
> "Install it in one command: `hivemind install claude-code`. It works with Claude Code, Cursor, Codex, any MCP client. Hivemind: your agents learn from each other's mistakes."

---

**Checklist before uploading**
- [ ] The first 30 seconds show a real moment, not a logo
- [ ] Every number on screen is one you measured
- [ ] Captions readable at 720p
- [ ] Repo link and live URL in the video description
