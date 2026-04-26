"""
GARCAR STRIPE REVENUE WEBHOOK
FastAPI endpoint that receives Stripe events and triggers reinvestment.
Deploy on AWS Lambda (via Mangum) or Vercel.
"""

import os
import json
import stripe
import boto3
import logging
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from reinvestment_loop import ReinvestmentLoop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stripe_revenue_webhook")

app = FastAPI(title="Garcar Revenue Webhook")

stripe.api_key          = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET         = os.getenv("STRIPE_WEBHOOK_SECRET")
reinvestment            = ReinvestmentLoop()
dynamo                  = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
conversions_table       = dynamo.Table("garcar-conversions")


@app.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature")
):
    body = await request.body()

    # Verify webhook signature
    try:
        event = stripe.Webhook.construct_event(body, stripe_signature, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        logger.warning("⚠️  Invalid Stripe webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    logger.info(f"📥 Stripe event: {event_type}")

    # ── Payment succeeded → trigger reinvestment ──────────────────────────────
    if event_type == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        result = reinvestment.process_payment(payment_intent)
        logger.info(f"💸 Reinvestment processed: {result}")

    # ── Checkout completed → mark conversion ─────────────────────────────────
    elif event_type == "checkout.session.completed":
        session = event["data"]["object"]
        persona_id = session.get("client_reference_id")
        if persona_id:
            try:
                conversions_table.update_item(
                    Key={"persona_id": persona_id},
                    UpdateExpression="SET converted = :c, converted_at = :t, stripe_session_id = :s",
                    ExpressionAttributeValues={
                        ":c": True,
                        ":t": session.get("created"),
                        ":s": session.get("id")
                    }
                )
                logger.info(f"✅ Conversion recorded for persona {persona_id}")
            except Exception as e:
                logger.error(f"Conversion update failed: {e}")

    # ── Subscription cancelled → flag for win-back ────────────────────────────
    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        logger.info(f"❌ Subscription cancelled: {subscription.get('id')} — queued for dead lead resurrection")
        # The resurrector will pick this up on its next 24hr cycle

    return JSONResponse({"received": True, "event": event_type})


@app.get("/health")
async def health():
    return {"status": "online", "engine": "garcar-revenue-v1"}


# AWS Lambda entry point via Mangum
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    pass  # Running on non-Lambda (ECS/Vercel)
