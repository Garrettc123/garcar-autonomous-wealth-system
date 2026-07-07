from types import SimpleNamespace

import stripe_webhook


def raise_publish_error(event):
    raise RuntimeError("bus down")


def test_revenue_event_publishes_payment_confirmed(monkeypatch):
    published = []
    fake_event = {
        "id": "evt_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_123",
                "payment_intent": "pi_123",
                "customer": "cus_123",
                "currency": "usd",
                "amount_total": 9900,
                "customer_details": {"email": "buyer@example.com"},
            }
        },
    }

    monkeypatch.setattr(
        stripe_webhook.stripe.Webhook,
        "construct_event",
        lambda payload, sig_header, secret: fake_event,
    )
    monkeypatch.setattr(
        stripe_webhook,
        "alw_run",
        lambda gross_revenue, source, log: SimpleNamespace(alw_total=gross_revenue),
    )
    monkeypatch.setattr(
        stripe_webhook.integration_event_bus,
        "publish_sync",
        lambda event: published.append(event),
    )

    result = stripe_webhook.handle_event(b"{}", "sig")

    assert result["status"] == "processed"
    assert result["integration_event_id"] == published[0]["event_id"]
    assert result["integration_event_status"] == "published"
    assert published[0]["event_type"] == "payment.confirmed"
    assert published[0]["entity_id"] == "pi_123"


def test_revenue_event_tolerates_event_bus_publish_failure(monkeypatch):
    fake_event = {
        "id": "evt_456",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_456",
                "payment_intent": "pi_456",
                "amount_total": 4900,
                "currency": "usd",
                "customer_details": {"email": "buyer@example.com"},
            }
        },
    }

    monkeypatch.setattr(
        stripe_webhook.stripe.Webhook,
        "construct_event",
        lambda payload, sig_header, secret: fake_event,
    )
    monkeypatch.setattr(
        stripe_webhook,
        "alw_run",
        lambda gross_revenue, source, log: SimpleNamespace(alw_total=gross_revenue),
    )
    monkeypatch.setattr(
        stripe_webhook.integration_event_bus,
        "publish_sync",
        raise_publish_error,
    )

    result = stripe_webhook.handle_event(b"{}", "sig")

    assert result["status"] == "processed"
    assert result["integration_event_status"] == "publish_failed"
