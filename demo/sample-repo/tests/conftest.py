import pytest

from payments import ledger


@pytest.fixture(autouse=True)
def fresh_ledger():
    return ledger.connect()
