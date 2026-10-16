"""`hivemind` command line."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from .config import Settings, slug

HOOK_EVENTS = [
    ("SessionStart", None, "session-start"),
    ("UserPromptSubmit", None, "prompt"),
    ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit", "pre-tool"),
    ("PostToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit", "post-tool"),
    ("PostToolUseFailure", "Bash", "post-tool-failure"),
    ("Stop", None, "stop"),
    ("SessionEnd", None, "session-end"),
]


def _hook_exe() -> str:
    found = shutil.which("hivemind-hook")
    if found:
        return found.replace("\\", "/")
    scripts = Path(sys.executable).parent
    for name in ("hivemind-hook.exe", "hivemind-hook"):
        if (scripts / name).exists():
            return str(scripts / name).replace("\\", "/")
    return "hivemind-hook"


def _merge_json(path: Path, update) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    update(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cmd_install(args) -> int:
    project = Path(args.dir).resolve()
    ws = slug(args.workspace or project.name)
    s = Settings.from_env()
    user = slug(args.user or s.user)
    url = (args.url or s.server_url).rstrip("/")
    headers = {
        "X-Hivemind-Workspace": ws,
        "X-Hivemind-User": user,
        "X-Hivemind-Client": args.client,
        # Overridable per terminal, so two agents on one machine can have different identities.
        "X-Hivemind-Agent": f"${{HIVEMIND_AGENT_ID:-{args.client}@{user}}}",
    }
    if s.api_key:
        headers["Authorization"] = "Bearer ${HIVEMIND_API_KEY}"

    if args.client == "claude-code":
        def add_server(d):
            d.setdefault("mcpServers", {})["hivemind"] = {"type": "http", "url": f"{url}/mcp", "headers": headers}

        _merge_json(project / ".mcp.json", add_server)
        exe = _hook_exe()

        def add_hooks(d):
            hooks = d.setdefault("hooks", {})
            for event, matcher, name in HOOK_EVENTS:
                groups = [g for g in hooks.get(event, [])
                          if not any("hivemind-hook" in h.get("command", "") for h in g.get("hooks", []))]
                entry = {"hooks": [{"type": "command", "timeout": 20,
                                    "command": f'"{exe}" {name} --workspace {ws} --user {user} --url {url}'}]}
                if matcher:
                    entry["matcher"] = matcher
                hooks[event] = groups + [entry]
            d.setdefault("enabledMcpjsonServers", [])
            if "hivemind" not in d["enabledMcpjsonServers"]:
                d["enabledMcpjsonServers"].append("hivemind")

        _merge_json(project / ".claude" / "settings.local.json", add_hooks)
        print(f"Claude Code: wrote {project / '.mcp.json'} and hooks in {project / '.claude' / 'settings.local.json'}")
    elif args.client == "cursor":
        def add_cursor(d):
            d.setdefault("mcpServers", {})["hivemind"] = {"url": f"{url}/mcp", "headers": {
                k: v.replace("${HIVEMIND_AGENT_ID:-cursor@" + user + "}", f"cursor@{user}") for k, v in headers.items()}}

        _merge_json(project / ".cursor" / "mcp.json", add_cursor)
        print(f"Cursor: wrote {project / '.cursor' / 'mcp.json'}")
    elif args.client == "codex":
        print("Add this to ~/.codex/config.toml:\n")
        print("[mcp_servers.hivemind]")
        print(f'url = "{url}/mcp"')
        h = ", ".join(f'"{k}" = "{v if "HIVEMIND_AGENT_ID" not in v else f"codex@{user}"}"' for k, v in headers.items())
        print(f"http_headers = {{ {h} }}")
    print(f"Workspace '{ws}', user '{user}', server {url}. Start the server with: hivemind serve")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def cmd_mcp(args) -> int:
    from .mcp_server import run_stdio

    run_stdio()
    return 0


def _hm():
    from .core import Hivemind

    return Hivemind(Settings.from_env())


def cmd_demo(args) -> int:
    from . import demo

    hm = _hm()
    res = demo.play(hm, slug(args.workspace), speed=args.speed, reset=not args.keep, history=not args.no_history)
    print(json.dumps(res, indent=2, default=str))
    return 0


def cmd_recall(args) -> int:
    from .core import Actor

    hm = _hm()
    a = Actor.from_settings(hm.settings, workspace=slug(args.workspace) if args.workspace else None)
    print(hm.recall(a, args.query, k=args.k, bump=False)["summary"])
    return 0


def cmd_consolidate(args) -> int:
    from .core import Actor

    hm = _hm()
    a = Actor.from_settings(hm.settings, workspace=slug(args.workspace) if args.workspace else None)
    print(json.dumps(hm.consolidate(a), indent=2))
    return 0


def cmd_doctor(args) -> int:
    import urllib.request

    s = Settings.from_env()
    ok = True
    try:
        from .db import GraphDB

        db = GraphDB(s.falkordb_url, 384)
        print(f"[ok] FalkorDB at {s.falkordb_url}: {len(db.list_graphs())} graphs")
    except Exception as exc:
        ok = False
        print(f"[!!] FalkorDB at {s.falkordb_url}: {exc}")
    try:
        with urllib.request.urlopen(f"{s.server_url}/api/health", timeout=3) as r:
            print(f"[ok] Hivemind server at {s.server_url}: {r.read().decode()}")
    except Exception as exc:
        ok = False
        print(f"[!!] Hivemind server at {s.server_url}: {exc} (run: hivemind serve)")
    print(f"[..] hook command: {_hook_exe()}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hivemind", description="Shared graph memory for AI agents (FalkorDB).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run API + dashboard + MCP (HTTP) server")
    sp.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    sp.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("mcp", help="run the MCP server over stdio")
    sp.set_defaults(fn=cmd_mcp)

    sp = sub.add_parser("install", help="connect an agent client to Hivemind in a project")
    sp.add_argument("client", choices=["claude-code", "cursor", "codex"])
    sp.add_argument("--dir", default=".")
    sp.add_argument("--workspace")
    sp.add_argument("--user")
    sp.add_argument("--url")
    sp.set_defaults(fn=cmd_install)

    sp = sub.add_parser("demo", help="play the scripted multi-agent scenario")
    sp.add_argument("--workspace", default="demo")
    sp.add_argument("--speed", type=float, default=1.0)
    sp.add_argument("--keep", action="store_true", help="don't reset the workspace first")
    sp.add_argument("--no-history", action="store_true", help="skip seeding last week's memory")
    sp.set_defaults(fn=cmd_demo)

    sp = sub.add_parser("recall", help="query memory from the terminal")
    sp.add_argument("query")
    sp.add_argument("--workspace")
    sp.add_argument("-k", type=int, default=8)
    sp.set_defaults(fn=cmd_recall)

    sp = sub.add_parser("consolidate", help="run PageRank / topics / archiving now")
    sp.add_argument("--workspace")
    sp.set_defaults(fn=cmd_consolidate)

    sp = sub.add_parser("doctor", help="check FalkorDB, server and hook setup")
    sp.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
