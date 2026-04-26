"""Autonomous Revenue Loop Tests"""
import asyncio
import pytest
from core.autonomous_revenue_loop import AutonomousRevenueLoop


@pytest.fixture
def loop_engine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return AutonomousRevenueLoop()


@pytest.mark.asyncio
async def test_full_cycle(loop_engine):
    leads = [
        {"email": f"lead{i}@test.com", "phone": "817-555-0001",
         "company": f"Co {i}", "budget": 1000 + i * 100}
        for i in range(10)
    ]
    result = await loop_engine.run_cycle(leads)
    assert result["cycle"] == 1
    assert result["leads_in"] == 10
    assert result["gross_revenue"] >= 0
    assert "net_retained" in result


@pytest.mark.asyncio
async def test_acquisition_phase(loop_engine):
    leads = [{"email": "x@y.com", "budget": 2000, "company": "BigCo"}]
    qualified = await loop_engine.acquire(leads)
    assert len(qualified) <= len(leads)
    for q in qualified:
        assert q["qualified"] is True


@pytest.mark.asyncio
async def test_reinvest_reduces_retained(loop_engine):
    net = 1000.0
    retained = await loop_engine.reinvest(net)
    assert retained < net
    assert loop_engine._total_reinvested > 0
