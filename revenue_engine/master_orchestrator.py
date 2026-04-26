"""
GARCAR REVENUE ENGINE — MASTER ORCHESTRATOR
The single entry point that wires all 7 layers together.

Data flow:
  SQS (signals) → PersonaSynthesizer → MultiVectorDeployer → Stripe
  Stripe webhook → ReinvestmentLoop → EventBridge → Google Ads budget
  DynamoDB scan  → DeadLeadResurrector → SQS (back to top)

Run this on an ECS Fargate task or EC2 instance with a cron trigger.
"""

import asyncio
import json
import os
import boto3
import logging
from signal_harvester    import SignalHarvester
from persona_synthesizer import PersonaSynthesizer
from multi_vector_deployer import MultiVectorDeployer
from dead_lead_resurrector import DeadLeadResurrector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("master_orchestrator")


class MasterOrchestrator:

    POLL_INTERVAL    = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    HARVEST_INTERVAL = int(os.getenv("HARVEST_INTERVAL_SECONDS", "900"))  # 15 min
    RESURRECT_INTERVAL = int(os.getenv("RESURRECT_INTERVAL_SECONDS", "86400"))  # 24 hr
    MAX_BATCH        = int(os.getenv("SQS_MAX_BATCH", "10"))

    def __init__(self):
        self.sqs       = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.queue_url = os.getenv("SIGNAL_QUEUE_URL")
        self.harvester  = SignalHarvester()
        self.synthesizer = PersonaSynthesizer()
        self.deployer   = MultiVectorDeployer()
        self.resurrector = DeadLeadResurrector()
        self._harvest_ticks = 0
        self._resurrect_ticks = 0

    def poll_signals(self):
        """Pull signals from SQS and process them."""
        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=self.MAX_BATCH,
                WaitTimeSeconds=20,  # Long poll
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
        except Exception as e:
            logger.error(f"SQS receive error: {e}")
            return

        messages = response.get("Messages", [])
        if not messages:
            return

        logger.info(f"📨 Processing {len(messages)} signals from queue")

        for msg in messages:
            try:
                signal = json.loads(msg["Body"])
                self._process_signal(signal)
                # Delete after successful processing
                self.sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=msg["ReceiptHandle"]
                )
            except Exception as e:
                logger.error(f"Signal processing failed: {e} | Message: {msg.get('MessageId')}")

    def _process_signal(self, signal: dict):
        """Full pipeline: signal → persona → deploy."""
        company = signal.get("company_name", "Unknown")
        logger.info(f"⚡ Processing signal: {signal.get('signal_type')} | {company}")

        # Synthesize persona
        persona = self.synthesizer.synthesize(signal)
        logger.info(
            f"🧠 Persona built: {persona.pain_category} | "
            f"{persona.urgency_level} | channel={persona.preferred_channel} | "
            f"tier={persona.offer_tier}"
        )

        # Deploy to channel
        self.deployer.deploy(persona)

    async def run_forever(self):
        """Main async loop — polls queue, runs harvest and resurrection on schedule."""
        logger.info("🚀 GARCAR REVENUE ENGINE ONLINE")
        logger.info(f"   Poll: every {self.POLL_INTERVAL}s | Harvest: every {self.HARVEST_INTERVAL}s | Resurrect: every {self.RESURRECT_INTERVAL}s")

        harvest_task    = asyncio.create_task(self.harvester.run_forever(self.HARVEST_INTERVAL))
        resurrect_task  = asyncio.create_task(self._resurrect_loop())
        process_task    = asyncio.create_task(self._process_loop())

        await asyncio.gather(harvest_task, resurrect_task, process_task)

    async def _process_loop(self):
        while True:
            self.poll_signals()
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _resurrect_loop(self):
        while True:
            await asyncio.sleep(self.RESURRECT_INTERVAL)
            self.resurrector.run_resurrection_cycle()


if __name__ == "__main__":
    orchestrator = MasterOrchestrator()
    asyncio.run(orchestrator.run_forever())
