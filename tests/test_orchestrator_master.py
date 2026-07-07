from types import SimpleNamespace

import orchestrator_master


def test_run_fulfillment_dispatches_payment_events(monkeypatch):
    orchestrator = orchestrator_master.MasterOrchestrator()
    orchestrator.metrics = orchestrator._init_metrics()

    event = {
        "event_id": "evt_payment_1",
        "event_type": "payment.confirmed",
        "entity_id": "pi_123",
    }
    published = []
    dispatched = []
    request_calls = []

    monkeypatch.setattr(
        orchestrator_master,
        "get_secret",
        lambda key, required=False: {
            "FULFILLMENT_WEBHOOK_URL": "https://example.com/fulfillment",
            "FULFILLMENT_WEBHOOK_SECRET": "super-secret",
        }.get(key),
    )
    monkeypatch.setattr(
        orchestrator_master.integration_event_bus,
        "read_events_sync",
        lambda **kwargs: [event],
    )
    monkeypatch.setattr(
        orchestrator_master.integration_event_bus,
        "is_dispatched_sync",
        lambda event_id: False,
    )
    monkeypatch.setattr(
        orchestrator_master.integration_event_bus,
        "mark_dispatched_sync",
        lambda event_id, **kwargs: dispatched.append((event_id, kwargs)),
    )
    monkeypatch.setattr(
        orchestrator_master.integration_event_bus,
        "publish_sync",
        lambda payload: published.append(payload),
    )
    monkeypatch.setattr(
        orchestrator_master.requests,
        "post",
        lambda *args, **kwargs: request_calls.append((args, kwargs)) or SimpleNamespace(
            status_code=202,
            raise_for_status=lambda: None,
        ),
    )

    orchestrator.run_fulfillment()

    assert orchestrator.metrics["fulfillment_dispatches"] == 1
    assert dispatched[0][0] == "evt_payment_1"
    assert published[0]["event_type"] == "fulfillment.started"
    assert request_calls[0][1]["headers"]["X-Garcar-Webhook-Secret"] == "super-secret"
