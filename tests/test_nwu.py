"""NWU Protocol Tests"""
import pytest
from core.nwu_protocol import NWUProtocol


@pytest.fixture
def protocol(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return NWUProtocol()


def test_mint(protocol):
    token = protocol.mint("test-node", "lead", {"email": "x@y.com"})
    assert token.token_id in protocol.ledger
    assert token.quality_score > 0.9  # email boosts quality


def test_usage_accrual(protocol):
    token = protocol.mint("test-node", "signal", {"value": 42})
    updated = protocol.record_usage(token.token_id, "consumer", revenue_delta=10.0)
    assert updated.usage_count == 1
    assert updated.revenue_attributed == 10.0


def test_settlement(protocol):
    token = protocol.mint("test-node", "event", {})
    protocol.record_usage(token.token_id, "consumer", revenue_delta=5.0)
    settled = protocol.settle(token.token_id)
    assert settled >= 0
    assert protocol.ledger[token.token_id].status == "settled"


def test_portfolio(protocol):
    for i in range(5):
        t = protocol.mint("n", "metric", {"i": i})
        protocol.record_usage(t.token_id, "c", revenue_delta=float(i))
    p = protocol.portfolio()
    assert p["active_tokens"] == 5
