import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    env: str
    ledger_url: str


def load() -> Config:
    env = os.environ.get("PAYMENTS_ENV", "production")
    urls = {"production": "https://ledger.internal", "test": "memory://ledger"}
    return Config(env=env, ledger_url=urls.get(env, urls["production"]))
