"""
GARCAR DEAD LEAD RESURRECTOR
Leads that didn't convert after 14 days get a completely new persona path.
New messaging angle. New channel. New offer framing.
This is the mechanism that makes the funnel never truly end.
"""

import os
import boto3
import logging
from datetime import datetime, timezone, timedelta
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger("dead_lead_resurrector")


class DeadLeadResurrector:

    RESURRECTION_DAYS = int(os.getenv("RESURRECTION_DAYS", "14"))

    def __init__(self):
        self.dynamo = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.conversions_table = self.dynamo.Table("garcar-conversions")
        self.signal_queue_url  = os.getenv("SIGNAL_QUEUE_URL")
        self.sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))

    def scan_for_dead_leads(self) -> list:
        """
        Scans DynamoDB for personas that:
        - Were deployed 14+ days ago
        - Never converted (converted=False)
        - Have not been resurrected yet (resurrected=False or missing)
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.RESURRECTION_DAYS)).isoformat()

        try:
            response = self.conversions_table.scan(
                FilterExpression=(
                    Attr("converted").eq(False) &
                    Attr("deployed_at").lt(cutoff) &
                    Attr("resurrected").not_exists()
                )
            )
            return response.get("Items", [])
        except Exception as e:
            logger.error(f"DynamoDB scan failed: {e}")
            return []

    def resurrect(self, dead_persona: dict):
        """
        Re-injects the lead into the signal queue with a new signal type
        that forces the persona synthesizer to take a different angle.
        """
        import json, uuid

        # Flip the channel — if email failed, try SMS next
        original_channel = dead_persona.get("channel", "email")
        new_channel_map = {"email": "sms", "sms": "ads", "ads": "email"}
        new_channel = new_channel_map.get(original_channel, "email")

        resurrected_signal = {
            "signal_id":        str(uuid.uuid4()),
            "signal_type":      "dead_lead_resurrection",
            "company_name":     dead_persona.get("company_name", ""),
            "contact_name":     dead_persona.get("contact_name", ""),
            "contact_email":    dead_persona.get("contact_email"),
            "contact_phone":    dead_persona.get("contact_phone"),
            "company_vertical": dead_persona.get("vertical", "general_contractor"),
            "raw_data":         {"resurrected_from": dead_persona.get("persona_id")},
            "intent_score":     0.70,  # Hard-floor intent — we already know they engaged once
            "forced_channel":   new_channel,
            "is_resurrection":  True,
            "original_persona": dead_persona.get("persona_id"),
        }

        try:
            self.sqs.send_message(
                QueueUrl=self.signal_queue_url,
                MessageBody=json.dumps(resurrected_signal),
                MessageAttributes={
                    "SignalType": {"StringValue": "dead_lead_resurrection", "DataType": "String"},
                    "IsResurrection": {"StringValue": "true", "DataType": "String"}
                }
            )
            # Mark original as resurrected
            self.conversions_table.update_item(
                Key={"persona_id": dead_persona["persona_id"]},
                UpdateExpression="SET resurrected = :r, resurrected_at = :t",
                ExpressionAttributeValues={
                    ":r": True,
                    ":t": datetime.now(timezone.utc).isoformat()
                }
            )
            logger.info(f"🔄 Resurrected lead: {dead_persona.get('company_name')} → new channel: {new_channel}")
        except Exception as e:
            logger.error(f"Resurrection failed for {dead_persona.get('persona_id')}: {e}")

    def run_resurrection_cycle(self):
        """Find all dead leads and resurrect them."""
        dead_leads = self.scan_for_dead_leads()
        logger.info(f"☠️  Found {len(dead_leads)} dead leads to resurrect")
        for lead in dead_leads:
            self.resurrect(lead)
        logger.info(f"✅ Resurrection cycle complete — {len(dead_leads)} leads re-entered pipeline")


if __name__ == "__main__":
    DeadLeadResurrector().run_resurrection_cycle()
