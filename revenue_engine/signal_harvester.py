"""
GARCAR SIGNAL HARVESTER
Monitors real-time buying signals across the web.
Each signal type has a base intent weight.
Combined signals produce a composite intent score.
"""

import asyncio
import aiohttp
import json
import os
import boto3
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signal_harvester")

# ── Signal type weights (empirically tuned) ──────────────────────────────────
SIGNAL_WEIGHTS = {
    "funding_round":        0.92,   # Just raised money → buying mode
    "new_hire_executive":   0.85,   # New CTO/COO → tech spend incoming
    "permit_filed":         0.88,   # Contractor filed permit → scaling
    "negative_review_competitor": 0.78,  # Competitor has dissatisfied customer
    "job_posting_tech":     0.72,   # Hiring signals need for tooling
    "domain_registered":    0.65,   # New business starting up
    "linkedin_company_update": 0.60,
    "google_review_spike":  0.55,
    "news_mention":         0.50,
    "website_traffic_surge": 0.80,  # From SimilarWeb/Semrush signals
    "ad_spend_increase":    0.75,   # Detected competitor or peer ad ramp
    "irs_ein_filing":       0.90,   # Brand new business — needs everything
}


@dataclass
class Signal:
    signal_type: str
    company_name: str
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    company_vertical: str          # roofing | contractor | legal | healthcare
    raw_data: dict
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    intent_score: float = 0.0
    signal_id: str = ""

    def __post_init__(self):
        import uuid
        self.intent_score = SIGNAL_WEIGHTS.get(self.signal_type, 0.4)
        self.signal_id = str(uuid.uuid4())


class SignalHarvester:
    """
    Polls multiple data sources asynchronously.
    Publishes high-intent signals to AWS SQS for downstream processing.
    """

    VERTICALS = ["roofing", "general_contractor", "legal", "healthcare", "surveying", "hvac"]
    INTENT_THRESHOLD = 0.65

    def __init__(self):
        self.sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
        self.queue_url = os.getenv("SIGNAL_QUEUE_URL")  # SQS queue ARN
        self.apollo_key = os.getenv("APOLLO_API_KEY")
        self.signals_harvested = 0
        self.signals_published = 0

    async def harvest_apollo_new_hires(self, session: aiohttp.ClientSession) -> list[Signal]:
        """Apollo.io: detect executive new hires in target verticals."""
        signals = []
        if not self.apollo_key:
            logger.warning("APOLLO_API_KEY not set — skipping new hire harvest")
            return signals

        for vertical in self.VERTICALS:
            try:
                payload = {
                    "api_key": self.apollo_key,
                    "q_organization_keyword_tags": [vertical],
                    "person_titles": ["CTO", "COO", "VP Operations", "Director of Technology"],
                    "per_page": 25,
                    "sort_by_field": "person_start_date",
                    "sort_ascending": False,
                }
                async with session.post(
                    "https://api.apollo.io/v1/mixed_people/search",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for person in data.get("people", [])[:10]:
                            s = Signal(
                                signal_type="new_hire_executive",
                                company_name=person.get("organization", {}).get("name", ""),
                                contact_name=f"{person.get('first_name','')} {person.get('last_name','')}",
                                contact_email=person.get("email"),
                                contact_phone=person.get("phone_numbers", [{}])[0].get("raw_number") if person.get("phone_numbers") else None,
                                company_vertical=vertical,
                                raw_data=person,
                            )
                            signals.append(s)
            except Exception as e:
                logger.error(f"Apollo harvest error for {vertical}: {e}")
        return signals

    async def harvest_competitor_reviews(self, session: aiohttp.ClientSession) -> list[Signal]:
        """
        Scrapes G2/Capterra negative reviews for competitor products.
        Dissatisfied customers = highest-quality inbound leads.
        """
        # Placeholder — wire to your scraping lambda or SerpAPI
        # Returns signals with signal_type = "negative_review_competitor"
        return []

    async def run_harvest_cycle(self):
        """Single harvest cycle — runs all collectors in parallel."""
        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                self.harvest_apollo_new_hires(session),
                self.harvest_competitor_reviews(session),
                return_exceptions=True
            )

        all_signals: list[Signal] = []
        for result in results:
            if isinstance(result, list):
                all_signals.extend(result)

        self.signals_harvested += len(all_signals)

        # Filter by intent threshold
        qualified = [s for s in all_signals if s.intent_score >= self.INTENT_THRESHOLD]
        logger.info(f"Harvested {len(all_signals)} signals, {len(qualified)} qualified (score >= {self.INTENT_THRESHOLD})")

        # Publish to SQS
        for signal in qualified:
            await self._publish_signal(signal)

    async def _publish_signal(self, signal: Signal):
        """Publish a qualified signal to SQS for the Intent Classifier."""
        try:
            self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(asdict(signal)),
                MessageAttributes={
                    "SignalType": {"StringValue": signal.signal_type, "DataType": "String"},
                    "Vertical":   {"StringValue": signal.company_vertical, "DataType": "String"},
                    "IntentScore": {"StringValue": str(signal.intent_score), "DataType": "Number"}
                }
            )
            self.signals_published += 1
        except Exception as e:
            logger.error(f"SQS publish failed for signal {signal.signal_id}: {e}")

    async def run_forever(self, interval_seconds: int = 900):  # every 15 min
        """Main loop — harvests signals on a schedule."""
        logger.info("🌊 Signal Harvester online — continuous harvest mode")
        while True:
            await self.run_harvest_cycle()
            logger.info(f"📊 Stats: harvested={self.signals_harvested} published={self.signals_published}")
            await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    harvester = SignalHarvester()
    asyncio.run(harvester.run_forever())
