from . import config

_entries: list[tuple[str, int]] = []


def connect():
    cfg = config.load()
    if cfg.ledger_url.startswith("https://"):
        raise RuntimeError(f"refusing to open ledger at {cfg.ledger_url} from this process")
    _entries.clear()
    return _entries


def record(kind: str, cents: int) -> None:
    _entries.append((kind, cents))
