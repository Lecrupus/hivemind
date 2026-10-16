"""Runtime settings, read from environment variables (HIVEMIND_*)."""

from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass, replace


def slug(value: str, default: str = "default") -> str:
    """Lowercase, filesystem- and key-safe identifier."""
    s = re.sub(r"[^a-zA-Z0-9_.-]+", "-", (value or "").strip().lower()).strip("-.")
    return s or default


def _default_user() -> str:
    try:
        return slug(getpass.getuser(), "dev")
    except Exception:
        return "dev"


@dataclass(frozen=True)
class Settings:
    falkordb_url: str = "redis://127.0.0.1:6379"
    workspace: str = "default"
    user: str = "dev"
    client: str = "custom"  # claude-code | cursor | codex | custom
    agent_id: str = ""  # defaults to "<client>@<user>"
    role: str | None = None  # optional: planner | coder | reviewer | ...
    server_url: str = "http://127.0.0.1:8765"
    embedder: str = "fastembed"  # fastembed | hash
    api_key: str | None = None
    model_cache: str = os.path.join(os.path.expanduser("~"), ".cache", "hivemind", "models")
    conflict_mode: str = "warn"  # warn | ask | off

    @property
    def resolved_agent_id(self) -> str:
        return self.agent_id or f"{self.client}@{self.user}"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        env = os.environ.get
        s = cls(
            falkordb_url=env("HIVEMIND_FALKORDB_URL", cls.falkordb_url),
            workspace=slug(env("HIVEMIND_WORKSPACE", "default")),
            user=slug(env("HIVEMIND_USER", "") or _default_user(), "dev"),
            client=slug(env("HIVEMIND_CLIENT", "custom")),
            agent_id=env("HIVEMIND_AGENT_ID", ""),
            role=env("HIVEMIND_ROLE") or None,
            server_url=env("HIVEMIND_URL", cls.server_url).rstrip("/"),
            embedder=env("HIVEMIND_EMBEDDER", cls.embedder),
            api_key=env("HIVEMIND_API_KEY") or None,
            model_cache=env("HIVEMIND_MODEL_CACHE", cls.model_cache),
            conflict_mode=env("HIVEMIND_CONFLICT_MODE", cls.conflict_mode),
        )
        return replace(s, **{k: v for k, v in overrides.items() if v is not None})
