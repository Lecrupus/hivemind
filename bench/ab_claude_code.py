"""A/B benchmark: the same real Claude Code task, with and without Hivemind.

Each run copies demo/sample-repo (a small payments service) to a fresh folder and
runs Claude Code headless on one task. Two scenarios (see SCENARIOS below):
  * in-repo: the team's rules are also written in the repo (docs, code, errors);
  * memory-only: the discount rules exist only in a teammate's earlier session,
    and the conventions doc is removed from the copy.
Both keep the test trap: the suite only runs with PAYMENTS_ENV=test.

  without  plain repo
  with     Hivemind installed (MCP + hooks), with the memory an earlier teammate's
           session would have left: the test procedure and the rounding convention.
           Memory is reset to that same state before every "with" run.

Turns, wall time and cost come from Claude Code's JSON output; correctness comes
from hidden acceptance checks run afterwards.

This uses YOUR Claude Code login and counts against your usage. It needs
`hivemind serve` running and FalkorDB up.

    uv run python bench/ab_claude_code.py --claude "C:/path/to/claude.exe" --runs 2
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from hivemind import cli
from hivemind.config import Settings
from hivemind.core import Actor, Hivemind
from hivemind.demo import reset_workspace

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "demo" / "sample-repo"
BENCH_DIR = ROOT / "src" / "hivemind" / "web" / "bench"
WORK = Path(os.path.expanduser("~")) / ".cache" / "hivemind" / "ab"
WORKSPACE = "ab-bench"

TASK = ("Add `apply_discount(total_cents: int, percent: float) -> int` to payments/discounts.py. It returns the "
        "order total after a percentage discount. Follow this team's conventions, add tests in "
        "tests/test_discounts.py, and make sure the whole test suite passes before you finish.")

TEST_PROCEDURE_FACTS = [
    ("Tests must run with PAYMENTS_ENV=test, otherwise the ledger refuses to open "
     "(RuntimeError: refusing to open ledger)", "gotcha", None, ["pytest", "payments/ledger.py"]),
]

# Two scenarios:
#  in-repo      every piece of knowledge is also written in the repo (docs/CONVENTIONS.md, the code, the error).
#  memory-only  the discount rules exist only as a decision a teammate recorded in an earlier session, and the
#               conventions doc is removed from the copy. This is what team memory is for: knowledge an agent
#               cannot recover from the code. It tests memory, not the model.
SCENARIOS = {
    "in-repo": {
        "out": "ab_in_repo.json",
        "title": "Knowledge also in the repo",
        "remove": [],
        "facts": TEST_PROCEDURE_FACTS + [
            ("Money is integer cents. Convert with payments.money.round_cents (rounds half-up); never use "
             "Python's round(), which rounds half-to-even", "convention", None, ["payments/money.py"]),
        ],
        "acceptance": """
from payments.discounts import apply_discount
assert apply_discount(1000, 12.5) == 875, apply_discount(1000, 12.5)
assert apply_discount(1005, 50) == 503, ("half-up rounding expected", apply_discount(1005, 50))
assert isinstance(apply_discount(999, 10), int)
print("ACCEPTANCE OK")
""",
    },
    "memory-only": {
        "out": "ab_memory_only.json",
        "title": "Knowledge only in team memory",
        "remove": ["docs/CONVENTIONS.md"],
        "facts": TEST_PROCEDURE_FACTS + [
            ("Finance decision (Oct 12): a discount can never exceed 50% of the order total; larger percentages "
             "are capped at 50%", "decision", "discounts.max_percent", ["payments/discounts.py"]),
            ("Discounted totals round DOWN to whole cents (math.floor), in the shop's favour; this is the one "
             "exception to round_cents", "decision", "discounts.rounding",
             ["payments/discounts.py", "payments/money.py"]),
        ],
        "acceptance": """
from payments.discounts import apply_discount
assert apply_discount(1000, 12.5) == 875, apply_discount(1000, 12.5)
assert apply_discount(1005, 50) == 502, ("round down expected", apply_discount(1005, 50))
assert apply_discount(1000, 80) == 500, ("50% cap expected", apply_discount(1000, 80))
assert isinstance(apply_discount(999, 10), int)
print("ACCEPTANCE OK")
""",
    },
}


def seed_memory(hm: Hivemind, scenario: dict) -> None:
    """What an earlier teammate's session (with Hivemind on) would have left behind."""
    reset_workspace(hm, WORKSPACE)
    alice = Actor(workspace=WORKSPACE, user="alice", agent_id="claude-code@alice", client="claude-code",
                  session_id="s_alice_earlier")
    hm.start_session(alice, alice.session_id)
    hm.remember(alice, "$ uv run --with pytest pytest -q\nfailed: RuntimeError: refusing to open ledger at "
                       "https://ledger.internal from this process", kind="error", about=["pytest"])
    hm.record_procedure(alice, "Run the payments test suite",
                        ["export PAYMENTS_ENV=test", "uv run --with pytest pytest -q"], about=["pytest"], auto=True)
    for statement, kind, key, about in scenario["facts"]:
        hm.learn(alice, statement, kind=kind, key=key, about=about, confidence=0.9)
    hm.end_session(alice)


def fresh_repo(name: str, scenario: dict) -> Path:
    d = WORK / name
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SAMPLE, d)
    for rel in scenario["remove"]:
        (d / rel).unlink(missing_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", "start"],
                   cwd=d, check=True)
    return d


def acceptance(repo: Path, scenario: dict) -> dict:
    env = {**os.environ, "PAYMENTS_ENV": "test"}
    suite = subprocess.run(["uv", "run", "--with", "pytest", "pytest", "-q"], cwd=repo, env=env,
                           capture_output=True, text=True, timeout=300)
    check = subprocess.run(["uv", "run", "python", "-c", scenario["acceptance"]], cwd=repo, env=env,
                           capture_output=True, text=True, timeout=300)
    return {"suite_passes": suite.returncode == 0, "acceptance_passes": "ACCEPTANCE OK" in check.stdout,
            "acceptance_output": (check.stdout + check.stderr)[-400:]}


def run_claude(claude: str, repo: Path, agent_id: str) -> dict:
    env = {**os.environ, "HIVEMIND_AGENT_ID": agent_id}
    proc = subprocess.run([claude, "-p", TASK, "--output-format", "json", "--dangerously-skip-permissions"],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=1800, encoding="utf-8")
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": (proc.stdout + proc.stderr)[-800:]}
    return {"turns": out.get("num_turns"), "duration_s": (out.get("duration_ms") or 0) / 1000,
            "cost_usd": out.get("total_cost_usd"), "is_error": out.get("is_error"),
            "result": (out.get("result") or "")[:600]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", default=os.environ.get("CLAUDE_BIN") or shutil.which("claude"))
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="memory-only")
    args = ap.parse_args()
    scenario = SCENARIOS[args.scenario]
    if not args.claude:
        sys.exit("Claude Code CLI not found: pass --claude PATH or set CLAUDE_BIN")
    settings = Settings.from_env()
    try:
        urllib.request.urlopen(f"{settings.server_url}/api/health", timeout=5)
    except Exception:
        sys.exit(f"Hivemind server not reachable at {settings.server_url}: run `hivemind serve` first")
    hm = Hivemind(settings)

    raw = []
    for i in range(args.runs):
        for variant in ("without", "with"):
            repo = fresh_repo(f"{args.scenario}-{variant}-{i}", scenario)
            if variant == "with":
                seed_memory(hm, scenario)
                cli.main(["install", "claude-code", "--dir", str(repo), "--workspace", WORKSPACE, "--user", "bench"])
            print(f"run {i + 1}/{args.runs} {variant} Hivemind ...", flush=True)
            r = {"variant": variant, "run": i, **run_claude(args.claude, repo, f"claude-code@bench-{variant}-{i}")}
            r.update(acceptance(repo, scenario))
            print("   ", {k: r.get(k) for k in ("turns", "duration_s", "cost_usd", "suite_passes", "acceptance_passes")},
                  flush=True)
            raw.append(r)

    def summary(variant: str, label: str) -> dict:
        rs = [r for r in raw if r["variant"] == variant and "turns" in r]
        mean = lambda k: statistics.mean(r[k] or 0 for r in rs) if rs else 0
        return {"variant": label, "runs": len(rs), "turns": mean("turns"), "duration_s": mean("duration_s"),
                "cost_usd": mean("cost_usd"),
                "correct": sum(r["acceptance_passes"] and r["suite_passes"] for r in rs)}

    result = {
        "agent": "Claude Code (headless, claude -p)",
        "scenario": args.scenario,
        "title": scenario["title"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "description": f"Same task on a fresh copy of demo/sample-repo, {args.runs} run(s) per variant. "
                       f"'With' starts from the memory a teammate's earlier session left. "
                       + ("The discount rules exist only in that memory; the conventions doc is removed."
                          if scenario["remove"] else "Everything memory knows is also written in the repo."),
        "metrics": ["turns", "duration_s", "cost_usd", "correct"],
        "labels": {"turns": "Agent turns", "duration_s": "Seconds", "cost_usd": "Cost (USD)",
                   "correct": "Correct runs (hidden checks)"},
        "runs": [summary("without", "Without Hivemind"), summary("with", "With Hivemind")],
        "raw": raw,
    }
    out = BENCH_DIR / scenario["out"]
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["runs"], indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
