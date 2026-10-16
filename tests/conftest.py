import uuid

import pytest

from hivemind.config import Settings
from hivemind.core import Actor, Hivemind
from hivemind.embeddings import HashEmbedder


@pytest.fixture(scope="session")
def hm():
    h = Hivemind(Settings.from_env(embedder="hash"), embedder=HashEmbedder())
    if not h.db.ping():
        pytest.skip("FalkorDB is not reachable (docker run -p 6379:6379 falkordb/falkordb)")
    return h


@pytest.fixture
def ws(hm):
    name = f"test-{uuid.uuid4().hex[:8]}"
    yield name
    for g in hm.db.list_graphs():
        if g == f"hivemind_{name}" or g.startswith(f"hivemind_{name}__"):
            hm.db.delete_graph(g)


@pytest.fixture
def agent(hm, ws):
    def make(user: str, client: str = "claude-code", role: str | None = None) -> Actor:
        a = Actor(workspace=ws, user=user, agent_id=f"{client}@{user}", client=client, role=role, cwd="/repo")
        hm.start_session(a, f"s_{user}_{uuid.uuid4().hex[:6]}")
        return a
    return make
