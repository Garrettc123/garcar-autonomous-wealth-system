"""Stripe Webhook Handler — Garcar Revenue Events
Handles all Stripe payment events and feeds confirmed revenue into ALW.
Deploy as a FastAPI route or AWS Lambda behind API Gateway.
"""
import json
import os
import stripe
from datetime import datetime
from typing import Dict

from abundance_wallet import run as alw_run
from core.event_bus import build_event, integration_event_bus

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

# Revenue events that trigger ALW allocation
REVENUE_EVENTS = {
    'checkout.session.completed',
    'invoice.payment_succeeded',
    'charge.succeeded',
}


def handle_event(payload: bytes, sig_header: str) -> Dict:
    """
    Verify Stripe signature and route the event.
    Call this from your FastAPI route or Lambda handler.
    """
    # Verify signature
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as e:
        print(f'Webhook signature failure: {e}')
        return {'status': 'error', 'reason': 'invalid_signature'}
    except Exception as e:
        print(f'Webhook parse error: {e}')
        return {'status': 'error', 'reason': str(e)}

    event_type = event['type']
    print(f'[Stripe Webhook] Received: {event_type}  id={event["id"]}')

    if event_type in REVENUE_EVENTS:
        return _handle_revenue_event(event)
    elif event_type == 'customer.subscription.deleted':
        return _handle_churn(event)
    elif event_type == 'invoice.payment_failed':
        return _handle_payment_failed(event)
    else:
        return {'status': 'ignored', 'event_type': event_type}


def _handle_revenue_event(event: Dict) -> Dict:
    """Extract amount, fire ALW allocation."""
    obj = event['data']['object']

    # Amount in cents → dollars
    if event['type'] == 'checkout.session.completed':
        amount = obj.get('amount_total', 0) / 100
        customer_email = obj.get('customer_details', {}).get('email', 'unknown')
    elif event['type'] == 'invoice.payment_succeeded':
        amount = obj.get('amount_paid', 0) / 100
        customer_email = obj.get('customer_email', 'unknown')
    else:  # charge.succeeded
        amount = obj.get('amount', 0) / 100
        customer_email = obj.get('billing_details', {}).get('email', 'unknown')

    if amount <= 0:
        return {'status': 'skipped', 'reason': 'zero_amount'}

    print(f'  Revenue confirmed: ${amount:.2f} from {customer_email}')

    # Feed into Abundance Living Wallet
    alw_dist = alw_run(
        gross_revenue=amount,
        source=f'stripe:{event["type"]}',
        log=True,
    )

    payment_event = build_event(
        "payment.confirmed",
        {
            "stripe_event_id": event["id"],
            "stripe_event_type": event["type"],
            "amount_usd": amount,
            "currency": obj.get("currency", "usd"),
            "customer_email": customer_email,
            "customer_id": obj.get("customer"),
            "checkout_session_id": obj.get("id"),
            "payment_intent_id": obj.get("payment_intent"),
            "subscription_id": obj.get("subscription"),
            "wallet_total": alw_dist.alw_total,
        },
        source="garcar-autonomous-wealth-system/stripe_webhook",
        entity_type="payment",
        entity_id=obj.get("payment_intent") or obj.get("id") or event["id"],
        correlation_id=event["id"],
        metadata={"provider": "stripe"},
    )
    integration_event_bus.publish_sync(payment_event)

    return {
        'status':         'processed',
        'event_type':     event['type'],
        'event_id':       event['id'],
        'amount':         amount,
        'customer_email': customer_email,
        'alw_total':      alw_dist.alw_total,
        'integration_event_id': payment_event['event_id'],
        'timestamp':      datetime.utcnow().isoformat() + 'Z',
    }


def _handle_churn(event: Dict) -> Dict:
    """Log subscription cancellation."""
    obj            = event['data']['object']
    customer_id    = obj.get('customer', 'unknown')
    cancel_at      = obj.get('canceled_at')
    print(f'  Churn: customer {customer_id} cancelled at {cancel_at}')
    return {'status': 'logged', 'event_type': 'churn', 'customer': customer_id}


def _handle_payment_failed(event: Dict) -> Dict:
    """Log failed payment for retry follow-up."""
    obj     = event['data']['object']
    email   = obj.get('customer_email', 'unknown')
    amount  = obj.get('amount_due', 0) / 100
    attempt = obj.get('attempt_count', 1)
    print(f'  Payment failed: ${amount:.2f} from {email} (attempt {attempt})')
    return {'status': 'logged', 'event_type': 'payment_failed',
            'email': email, 'amount': amount, 'attempt': attempt}


# ── FastAPI route (used by dashboard_api.py) ─────────────────────────────────
try:
    from fastapi import FastAPI, Request, HTTPException

    def register_webhook_route(app: FastAPI):
        @app.post('/webhook/stripe')
        async def stripe_webhook_endpoint(request: Request):
            payload    = await request.body()
            sig_header = request.headers.get('stripe-signature', '')
            result     = handle_event(payload, sig_header)
            if result.get('status') == 'error':
                raise HTTPException(status_code=400, detail=result['reason'])
            return result
except ImportError:
    def register_webhook_route(app):
        print('FastAPI not available — webhook route not registered')


# ── AWS Lambda handler ────────────────────────────────────────────────────────
def lambda_handler(event: Dict, context) -> Dict:
    """AWS Lambda entry point for API Gateway proxy integration."""
    body       = event.get('body', '')
    sig_header = event.get('headers', {}).get('stripe-signature', '')

    if isinstance(body, str):
        body = body.encode('utf-8')

    result = handle_event(body, sig_header)
    status = 400 if result.get('status') == 'error' else 200
    return {
        'statusCode': status,
        'body': json.dumps(result),
        'headers': {'Content-Type': 'application/json'},
    }


if __name__ == '__main__':
    # Manual test with a fake checkout event
    import hmac, hashlib, time
    test_payload = json.dumps({
        'id':   'evt_test_001',
        'type': 'checkout.session.completed',
        'data': {'object': {
            'amount_total': 9900,
            'customer_details': {'email': 'test@example.com'}
        }}
    }).encode()
    ts  = str(int(time.time()))
    sig = hmac.new(WEBHOOK_SECRET.encode() or b'test_secret',
                   f'{ts}.'.encode() + test_payload, hashlib.sha256).hexdigest()
    print(handle_event(test_payload, f't={ts},v1={sig}'))
