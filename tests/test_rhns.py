"""RHNS Engine Tests"""
import asyncio
import pytest
from core.rhns_engine import RHNSEngine, NetworkNode, NodeTier, NodeState


@pytest.fixture
def engine():
    return RHNSEngine()


@pytest.mark.asyncio
async def test_register_node(engine):
    node = NetworkNode(name="test-agent", tier=NodeTier.AGENT,
                       domain="test", capabilities=["cap_a"])
    node_id = await engine.register(node)
    assert node_id in engine.nodes
    assert engine.nodes[node_id].name == "test-agent"


@pytest.mark.asyncio
async def test_route_task(engine):
    node = NetworkNode(name="worker", tier=NodeTier.AGENT,
                       domain="test", capabilities=["do_work"],
                       state=NodeState.ACTIVE)
    await engine.register(node)
    task_id = await engine.route_task("do_work", {"data": "payload"})
    assert task_id is not None


@pytest.mark.asyncio
async def test_no_capable_node(engine):
    task_id = await engine.route_task("nonexistent_cap", {})
    assert task_id is None


@pytest.mark.asyncio
async def test_heartbeat_updates_state(engine):
    node = NetworkNode(name="hb-node", tier=NodeTier.AGENT, domain="test",
                       capabilities=["ping"])
    nid = await engine.register(node)
    await engine.heartbeat(nid, {"tasks_completed": 5, "revenue_delta": 50.0})
    assert engine.nodes[nid].tasks_completed == 5
    assert engine.nodes[nid].revenue_generated == 50.0


@pytest.mark.asyncio
async def test_discover(engine):
    node = NetworkNode(name="d-node", tier=NodeTier.AGENT, domain="test",
                       capabilities=["sense"])
    await engine.register(node)
    snapshot = await engine.discover()
    assert snapshot["total_nodes"] >= 1
    assert "network_health" in snapshot
