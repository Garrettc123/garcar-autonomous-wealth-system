import pytest

from core.event_bus import IntegrationEventBus, build_event


@pytest.mark.asyncio
async def test_event_bus_memory_publish_and_read():
    bus = IntegrationEventBus(use_redis=False)
    event = build_event(
        "payment.confirmed",
        {"amount_usd": 99.0},
        entity_type="payment",
        entity_id="pi_123",
    )

    await bus.publish_event(event)
    events = await bus.read_events(event_type="payment.confirmed")
    health = await bus.get_health()

    assert events[-1]["event_id"] == event["event_id"]
    assert health["backend"] == "memory"
    assert health["buffered_events"] >= 1


@pytest.mark.asyncio
async def test_event_bus_tracks_dispatched_ids():
    bus = IntegrationEventBus(use_redis=False)
    event = build_event("payment.confirmed", {"amount_usd": 49.0})
    await bus.publish_event(event)

    assert await bus.is_dispatched(event["event_id"]) is False
    await bus.mark_dispatched(event["event_id"], dispatcher="fulfillment")
    assert await bus.is_dispatched(event["event_id"]) is True
