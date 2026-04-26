"""
GARCAR REINVESTMENT LOOP
Every Stripe payment auto-reinvests 15% into the next ad cycle.
This makes the revenue engine self-funding — it grows without human budget decisions.

Trigger: Stripe webhook → payment_intent.succeeded
Action:  15% of payment amount queued to Google Ads budget via AWS EventBridge
"""

import os
import json
import boto3
import stripe
import logging
from datetime import datetime, timezone

logger = logging.getLogger("reinvestment_loop")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

REINVESTMENT_RATE = float(os.getenv("REINVESTMENT_RATE", "0.15"))  # 15% default


class ReinvestmentLoop:

    def __init__(self):
        self.events = boto3.client("events", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.dynamo  = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.ledger  = self.dynamo.Table("garcar-reinvestment-ledger")
        self.event_bus = os.getenv("EVENTBRIDGE_BUS_NAME", "garcar-revenue-bus")

    def process_payment(self, payment_intent: dict):
        """
        Called when a Stripe payment succeeds.
        Calculates reinvestment amount and queues it to EventBridge.
        """
        amount_cents   = payment_intent.get("amount", 0)
        amount_dollars = amount_cents / 100
        reinvest_amount = round(amount_dollars * REINVESTMENT_RATE, 2)
        keep_amount     = round(amount_dollars - reinvest_amount, 2)

        logger.info(
            f"💰 Payment received: ${amount_dollars:.2f} | "
            f"Reinvesting: ${reinvest_amount:.2f} (15%) | "
            f"Net revenue: ${keep_amount:.2f}"
        )

        # Queue reinvestment event to EventBridge
        event = {
            "EventBusName": self.event_bus,
            "Source": "garcar.reinvestment",
            "DetailType": "AdBudgetAllocation",
            "Detail": json.dumps({
                "payment_intent_id": payment_intent.get("id"),
                "customer_id":       payment_intent.get("customer"),
                "original_amount":   amount_dollars,
                "reinvest_amount":   reinvest_amount,
                "currency":          payment_intent.get("currency", "usd"),
                "timestamp":         datetime.now(timezone.utc).isoformat(),
                "vertical":          payment_intent.get("metadata", {}).get("vertical", "unknown"),
                "channel":           payment_intent.get("metadata", {}).get("channel", "unknown"),
            })
        }

        try:
            self.events.put_events(Entries=[event])
            logger.info(f"📡 EventBridge: queued ${reinvest_amount:.2f} ad budget allocation")
        except Exception as e:
            logger.error(f"EventBridge publish failed: {e}")

        # Persist to ledger
        self._write_ledger(payment_intent, reinvest_amount, keep_amount)

        return {
            "original": amount_dollars,
            "reinvested": reinvest_amount,
            "net_revenue": keep_amount
        }

    def _write_ledger(self, payment_intent: dict, reinvest: float, net: float):
        try:
            self.ledger.put_item(Item={
                "payment_intent_id": payment_intent.get("id"),
                "customer_id":       payment_intent.get("customer", ""),
                "gross_amount":      str(payment_intent.get("amount", 0) / 100),
                "reinvest_amount":   str(reinvest),
                "net_revenue":       str(net),
                "timestamp":         datetime.now(timezone.utc).isoformat(),
                "vertical":          payment_intent.get("metadata", {}).get("vertical", ""),
            })
        except Exception as e:
            logger.error(f"Ledger write failed: {e}")
