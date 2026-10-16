"""`hivemind-hook <event>`: the command Claude Code runs for each hook.

Deliberately stdlib-only and tiny: it forwards the hook payload to the
running Hivemind server (which has the embedding model warm) and prints the
server's JSON reply. If the server is down it exits 0 silently, so a memory
outage never blocks the agent."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

TIMEOUTS = {"session-start": 15, "prompt": 10}


def _arg(flag: str, argv: list[str]) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _branch(cwd: str | None) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd or None, capture_output=True,
                             text=True, timeout=2)
        return out.stdout.strip() or None
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    event = argv[0] if argv else ""
    env = os.environ.get
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if event == "session-start":
        payload["_branch"] = _branch(payload.get("cwd"))

    base = (env("HIVEMIND_URL") or _arg("--url", argv) or "http://127.0.0.1:8765").rstrip("/")
    user = env("HIVEMIND_USER") or _arg("--user", argv) or ""
    client = env("HIVEMIND_CLIENT") or _arg("--client", argv) or "claude-code"
    headers = {
        "Content-Type": "application/json",
        "X-Hivemind-Workspace": env("HIVEMIND_WORKSPACE") or _arg("--workspace", argv) or "default",
        "X-Hivemind-User": user,
        "X-Hivemind-Client": client,
        "X-Hivemind-Agent": env("HIVEMIND_AGENT_ID") or _arg("--agent", argv) or "",
        "X-Hivemind-Role": env("HIVEMIND_ROLE") or _arg("--role", argv) or "",
    }
    if env("HIVEMIND_API_KEY"):
        headers["Authorization"] = f"Bearer {env('HIVEMIND_API_KEY')}"
    req = urllib.request.Request(f"{base}/api/hook/{event}", data=json.dumps(payload).encode(), headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUTS.get(event, 8)) as resp:
            body = resp.read().decode("utf-8").strip()
        if body and body != "{}":
            sys.stdout.write(body)
    except Exception:
        if event == "session-start":
            sys.stdout.write(json.dumps({"systemMessage": f"Hivemind server not reachable at {base}; "
                                                          "team memory is off for this session (run: hivemind serve)."}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
