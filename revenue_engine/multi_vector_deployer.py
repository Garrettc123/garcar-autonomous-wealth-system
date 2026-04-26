"""
GARCAR MULTI-VECTOR DEPLOYER
Takes a synthesized persona and fires the offer across the best channel.
All conversion links are tracked Stripe checkout sessions.
"""

import os
import boto3
import stripe
import logging
from twilio.rest import Client as TwilioClient
from dataclasses import asdict
import json

logger = logging.getLogger("multi_vector_deployer")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


class MultiVectorDeployer:

    BASE_URL = os.getenv("DASHBOARD_URL", "https://app.garcar.io")

    def __init__(self):
        self.ses   = boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.twilio = TwilioClient(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        self.dynamo = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.conversions_table = self.dynamo.Table("garcar-conversions")

    # ── Stripe Checkout Session ────────────────────────────────────────────────

    def create_checkout_session(self, persona) -> str:
        """Create a tracked Stripe checkout session for this persona."""
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": persona.stripe_price_id, "quantity": 1}],
            success_url=f"{self.BASE_URL}/success?persona={persona.persona_id}",
            cancel_url=f"{self.BASE_URL}/cancel?persona={persona.persona_id}",
            client_reference_id=persona.persona_id,
            metadata={
                "persona_id":    persona.persona_id,
                "signal_id":     persona.signal_id,
                "company_name":  persona.company_name,
                "vertical":      persona.vertical,
                "channel":       persona.preferred_channel,
            },
            allow_promotion_codes=True,
        )
        self._log_deployment(persona, session.url)
        return session.url

    # ── SMS Deploy ────────────────────────────────────────────────────────────

    def deploy_sms(self, persona, checkout_url: str):
        """Send a hyper-personalized SMS to the contact."""
        if not persona.contact_phone:
            logger.warning(f"No phone for persona {persona.persona_id} — skipping SMS")
            return

        message_body = (
            f"{persona.headline}\n\n"
            f"{persona.subheadline}\n\n"
            f"→ {checkout_url}\n"
            f"Reply STOP to opt out."
        )

        # Enforce 160-char SMS safe length
        if len(message_body) > 320:
            message_body = f"{persona.headline}\n→ {checkout_url}\nReply STOP to opt out."

        try:
            msg = self.twilio.messages.create(
                body=message_body,
                from_=os.getenv("TWILIO_FROM_NUMBER"),
                to=persona.contact_phone,
            )
            logger.info(f"📱 SMS sent to {persona.contact_phone} — SID: {msg.sid}")
        except Exception as e:
            logger.error(f"SMS deploy failed: {e}")

    # ── Email Deploy ──────────────────────────────────────────────────────────

    def deploy_email(self, persona, checkout_url: str):
        """Send a rich HTML email via AWS SES."""
        if not persona.contact_email:
            logger.warning(f"No email for persona {persona.persona_id} — skipping email")
            return

        html = self._build_email_html(persona, checkout_url)

        try:
            self.ses.send_email(
                Source=os.getenv("SES_SENDER_EMAIL", "noreply@garcar.io"),
                Destination={"ToAddresses": [persona.contact_email]},
                Message={
                    "Subject": {"Data": persona.headline, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html, "Charset": "UTF-8"},
                        "Text": {"Data": f"{persona.headline}\n{persona.subheadline}\n\n{checkout_url}\n\nUnsubscribe: {self.BASE_URL}/unsubscribe", "Charset": "UTF-8"}
                    }
                },
                Tags=[{"Name": "vertical", "Value": persona.vertical}, {"Name": "tier", "Value": persona.offer_tier}]
            )
            logger.info(f"📧 Email sent to {persona.contact_email}")
        except Exception as e:
            logger.error(f"SES email deploy failed: {e}")

    def _build_email_html(self, persona, checkout_url: str) -> str:
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:12px;overflow:hidden;">
        <tr><td style="background:linear-gradient(135deg,#00ff88,#00b4d8);padding:4px;"></td></tr>
        <tr><td style="padding:48px 40px;">
          <p style="color:#00ff88;font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;margin:0 0 16px;">GARCAR AI — {persona.vertical.upper()} INTELLIGENCE</p>
          <h1 style="color:#ffffff;font-size:28px;font-weight:800;line-height:1.2;margin:0 0 20px;">{persona.headline}</h1>
          <p style="color:#aaa;font-size:16px;line-height:1.6;margin:0 0 32px;">{persona.subheadline}</p>
          <a href="{checkout_url}" style="display:inline-block;background:linear-gradient(135deg,#00ff88,#00b4d8);color:#000;font-weight:800;font-size:15px;padding:16px 36px;border-radius:8px;text-decoration:none;">{persona.cta_text}</a>
          <p style="color:#555;font-size:12px;margin:32px 0 0;">You're receiving this because {persona.company_name} matched our growth signal criteria.<br>
          <a href="{self.BASE_URL}/unsubscribe" style="color:#555;">Unsubscribe</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    # ── Deploy Router ─────────────────────────────────────────────────────────

    def deploy(self, persona):
        """Route deployment to best channel for this persona."""
        checkout_url = self.create_checkout_session(persona)

        channel = persona.preferred_channel
        logger.info(f"🚀 Deploying persona {persona.persona_id} via {channel.upper()} | {persona.company_name}")

        if channel == "sms":
            self.deploy_sms(persona, checkout_url)
        elif channel == "email":
            self.deploy_email(persona, checkout_url)
        elif channel == "ads":
            logger.info(f"📣 Queued for Google Ads — persona {persona.persona_id} | URL: {checkout_url}")
            # Wire to reinvestment_loop.py Google Ads queue

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log_deployment(self, persona, checkout_url: str):
        """Write deployment record to DynamoDB for tracking."""
        try:
            self.conversions_table.put_item(Item={
                "persona_id":     persona.persona_id,
                "signal_id":      persona.signal_id,
                "company_name":   persona.company_name,
                "vertical":       persona.vertical,
                "channel":        persona.preferred_channel,
                "checkout_url":   checkout_url,
                "offer_tier":     persona.offer_tier,
                "stripe_price_id":persona.stripe_price_id,
                "deployed_at":    persona.created_at,
                "converted":      False,
            })
        except Exception as e:
            logger.error(f"DynamoDB log failed: {e}")
