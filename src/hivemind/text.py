"""Text helpers: entity extraction, shell-command keys, secret redaction, time."""

from __future__ import annotations

import re
import shlex
import time
import uuid

# --- ids & time -------------------------------------------------------------


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_ms() -> int:
    return int(time.time() * 1000)


def ago(ts_ms: int | None, now: int | None = None) -> str:
    if not ts_ms:
        return "unknown"
    secs = max(0, ((now or now_ms()) - int(ts_ms)) // 1000)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit} ago"
    return "just now"


def clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- secret redaction ----------------------------------------------------------

_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)(\s*[:=]\s*)([^\s'\"]{4,})"),
     r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(://[^:/\s]+:)([^@/\s]{3,})(@)"), r"\1[REDACTED]\3"),  # creds in URLs
]


def redact(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


# --- entity extraction ------------------------------------------------------------

_EXT = (
    "py|pyi|ts|tsx|js|jsx|mjs|cjs|json|md|mdx|ya?ml|toml|ini|cfg|conf|go|rs|java|kt|rb|php|cs|"
    "cpp|cc|c|h|hpp|swift|sql|sh|ps1|bat|css|scss|html|vue|svelte|lock|env|txt|proto|graphql|tf|lua|dart"
)
_FILE_RE = re.compile(rf"(?<![\w@/.-])((?:\.{{0,2}}/)?(?:[\w.-]+/)*[\w-]+\.(?:{_EXT}))(?![\w/])", re.I)
_SPECIAL_FILES = re.compile(r"\b(Dockerfile|Makefile|docker-compose\.ya?ml|package\.json|pyproject\.toml|"
                            r"Cargo\.toml|go\.mod|requirements\.txt|\.env(?:\.\w+)?)\b")
_BACKTICK_RE = re.compile(r"`([^`\n]{2,80})`")

COMMANDS = {
    "npm", "pnpm", "yarn", "bun", "npx", "bunx", "pip", "pip3", "uv", "poetry", "pytest", "python", "python3",
    "node", "deno", "docker", "docker-compose", "podman", "make", "cargo", "go", "git", "gh", "kubectl", "helm",
    "terraform", "gradle", "gradlew", "mvn", "dotnet", "jest", "vitest", "ruff", "mypy", "black", "eslint",
    "prettier", "tsc", "prisma", "alembic", "psql", "mysql", "redis-cli", "curl", "rails", "rake", "bundle",
    "composer", "php", "mix", "flutter", "swift", "xcodebuild", "playwright", "cypress", "tox", "nox",
}
# Commands that take a meaningful sub-command ("npm test", "docker compose").
_SUBCOMMAND_TOOLS = {"npm", "pnpm", "yarn", "bun", "uv", "poetry", "docker", "cargo", "go", "make", "dotnet",
                     "gradle", "mvn", "kubectl", "helm", "terraform", "prisma", "alembic", "rails", "mix",
                     "flutter", "git", "gh", "composer", "bundle", "deno"}
# Read-only commands that never count as a step of a procedure.
_INSPECT_ONLY = {"ls", "dir", "cat", "type", "head", "tail", "less", "more", "grep", "rg", "find", "pwd", "echo",
                 "which", "where", "cd", "tree", "wc", "file", "stat", "env", "printenv", "whoami", "date", "clear"}
_INSPECT_SUBCOMMANDS = {("git", "status"), ("git", "log"), ("git", "diff"), ("git", "show"), ("git", "branch"),
                        ("docker", "ps"), ("docker", "images"), ("docker", "logs"), ("kubectl", "get")}


def entity_id(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().strip("./").lower())


def _entity(name: str, etype: str) -> dict:
    return {"id": entity_id(name), "name": name.strip(), "type": etype}


def classify(name: str) -> str:
    n = name.strip()
    if _FILE_RE.fullmatch(n) or _SPECIAL_FILES.fullmatch(n) or "/" in n:
        return "file"
    first = n.split()[0].lower() if n.split() else ""
    if first in COMMANDS:
        return "command"
    return "concept"


def extract_entities(text: str, about: list[str] | None = None, limit: int = 12) -> list[dict]:
    """Pull file paths, commands and `code spans` out of free text."""
    found: dict[str, dict] = {}

    def add(name: str, etype: str):
        name = name.strip().strip(".,;:()[]{}\"'")
        if len(name) < 2 or len(name) > 80:
            return
        e = _entity(name, etype)
        found.setdefault(e["id"], e)

    for a in about or []:
        if a and a.strip():
            add(a, classify(a))
    for m in _FILE_RE.finditer(text or ""):
        add(m.group(1), "file")
    for m in _SPECIAL_FILES.finditer(text or ""):
        add(m.group(1), "file")
    for m in _BACKTICK_RE.finditer(text or ""):
        span = m.group(1).strip()
        key = command_key(span)
        if key:
            add(key, "command")
        elif len(span.split()) <= 4:
            add(span, classify(span))
    return list(found.values())[:limit]


# --- shell commands ---------------------------------------------------------------


def _tokens(cmd: str) -> list[str]:
    cmd = cmd.strip()
    # Only the first command of a pipeline / chain is considered.
    cmd = re.split(r"\s*(?:\|\||&&|;|\|)\s*", cmd, maxsplit=1)[0]
    try:
        toks = shlex.split(cmd, posix=True)
    except ValueError:
        toks = cmd.split()
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):  # FOO=bar cmd
        toks.pop(0)
    while toks and toks[0] in {"sudo", "time", "exec", "nohup"}:
        toks.pop(0)
    if len(toks) > 2 and toks[0] in {"uv", "poetry", "pipenv", "hatch", "pdm"} and toks[1] == "run":
        toks = toks[2:]  # "uv run pytest" -> "pytest"
    return toks


def command_key(cmd: str) -> str | None:
    """Normalise a shell command to the 'thing it runs': `npm test`, `pytest`, `docker compose`."""
    toks = _tokens(cmd or "")
    if not toks:
        return None
    head = toks[0].replace("\\", "/").split("/")[-1].lower()
    head = re.sub(r"\.(exe|cmd|bat)$", "", head)
    if head in {"python", "python3", "py"} and len(toks) >= 3 and toks[1] == "-m":
        return toks[2].lower()
    if head == "npx" or head == "bunx":
        return toks[1].lower() if len(toks) > 1 else head
    if head in {"npm", "pnpm", "yarn", "bun"} and len(toks) > 1 and toks[1] == "run" and len(toks) > 2:
        return f"{head} {toks[2]}".lower()
    if head in _SUBCOMMAND_TOOLS and len(toks) > 1 and not toks[1].startswith("-"):
        return f"{head} {toks[1]}".lower()
    if head in COMMANDS or head in _INSPECT_ONLY:
        return head
    if head.startswith("./") or "/" in toks[0]:
        return head
    return head if re.fullmatch(r"[a-z0-9_.-]{2,30}", head) else None


def normalize_command(cmd: str) -> str:
    """Canonical form for comparing steps: `uv run pytest -q` == `pytest -q`."""
    toks = _tokens(cmd or "")
    if len(toks) >= 3 and toks[0].lower() in {"python", "python3", "py"} and toks[1] == "-m":
        toks = toks[2:]
    if toks and toks[0].lower() in {"npx", "bunx"}:
        toks = toks[1:]
    return " ".join(toks).lower() if toks else re.sub(r"\s+", " ", (cmd or "").strip().lower())


def module_of(path: str) -> str | None:
    """Parent directory of a file entity, used to group files into modules."""
    parts = path.replace("\\", "/").strip("./").split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else None


def is_inspect_only(cmd: str) -> bool:
    toks = _tokens(cmd or "")
    if not toks:
        return True
    head = toks[0].lower()
    if head in _INSPECT_ONLY:
        return True
    return len(toks) > 1 and (head, toks[1].lower()) in _INSPECT_SUBCOMMANDS


_EXC_LINE = re.compile(r"\b[A-Z]\w*(?:Error|Exception|Exit)\b|\b(?:error|fatal|ERR!)\s*[:\[]")
_HINT_LINE = re.compile(r"(?i)not found|cannot|can't|refused|denied|missing|no such|timed? ?out|unable to")
_SUMMARY_LINE = re.compile(r"(?i)^(?:=+|-+|FAILED\b|ERROR\b\s+\S+::|\W*\d+\s+(?:failed|passed|errors?|warnings?)\b|exit code)")


def error_signature(error: str) -> str:
    """The root-cause line of an error, with volatile bits (numbers, addresses) masked.

    Prefers the first exception-like line (`psycopg.OperationalError: ...`) over
    test-runner summaries (`1 failed, 41 errors in 3.2s`)."""
    lines = [re.sub(r"^E\s+", "", ln.strip()) for ln in (error or "").splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _SUMMARY_LINE.search(ln)] or lines
    pick = next((ln for ln in lines if _EXC_LINE.search(ln)), None) \
        or next((ln for ln in lines if _HINT_LINE.search(ln)), None) \
        or (lines[-1] if lines else "")
    pick = re.sub(r"0x[0-9a-fA-F]+|\b\d+(?:\.\d+)*\b", "#", pick)
    return clip(pick, 200)
