"""
GARCAR PERSONA SYNTHESIZER
Transforms raw signals into psychographic personas.
Each persona determines messaging tone, offer angle, and channel priority.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional
from openai import OpenAI
import logging

logger = logging.getLogger("persona_synthesizer")


@dataclass
class Persona:
    signal_id: str
    company_name: str
    contact_name: str
    contact_email: Optional[str]
    contact_phone: Optional[str]
    vertical: str

    # Psychographic profile
    pain_category: str          # cash_flow | operational_chaos | growth_ceiling | competitive_threat
    urgency_level: str          # immediate | this_week | this_month
    decision_style: str         # analytical | emotional | social_proof | authority
    preferred_channel: str      # sms | email | ads | linkedin
    price_sensitivity: str      # price_sensitive | value_buyer | premium_buyer

    # Generated offer
    headline: str = ""
    subheadline: str = ""
    cta_text: str = ""
    offer_tier: str = ""        # basic | pro | enterprise
    stripe_price_id: str = ""

    # Tracking
    persona_id: str = ""
    created_at: str = ""


VERTICAL_PAIN_MAP = {
    "roofing":             "cash_flow",
    "general_contractor":  "operational_chaos",
    "legal":               "growth_ceiling",
    "healthcare":          "operational_chaos",
    "surveying":           "competitive_threat",
    "hvac":                "cash_flow",
}

SIGNAL_URGENCY_MAP = {
    "funding_round":             "this_week",
    "new_hire_executive":        "this_week",
    "permit_filed":              "immediate",
    "negative_review_competitor":"immediate",
    "irs_ein_filing":            "immediate",
    "job_posting_tech":          "this_month",
    "domain_registered":         "this_week",
    "website_traffic_surge":     "this_week",
    "ad_spend_increase":         "this_month",
}

OFFER_TIER_MAP = {
    "immediate":   {"tier": "pro",        "price_env": "STRIPE_PRICE_PRO"},
    "this_week":   {"tier": "basic",      "price_env": "STRIPE_PRICE_BASIC"},
    "this_month":  {"tier": "enterprise", "price_env": "STRIPE_PRICE_ENTERPRISE"},
}


class PersonaSynthesizer:

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def synthesize(self, signal: dict) -> Persona:
        """Build a full persona from a signal dict."""
        import uuid
        from datetime import datetime, timezone

        vertical = signal.get("company_vertical", "general_contractor")
        signal_type = signal.get("signal_type", "domain_registered")
        urgency = SIGNAL_URGENCY_MAP.get(signal_type, "this_month")
        pain = VERTICAL_PAIN_MAP.get(vertical, "operational_chaos")
        offer_config = OFFER_TIER_MAP[urgency]

        persona = Persona(
            signal_id=signal["signal_id"],
            company_name=signal.get("company_name", "Your Business"),
            contact_name=signal.get("contact_name", ""),
            contact_email=signal.get("contact_email"),
            contact_phone=signal.get("contact_phone"),
            vertical=vertical,
            pain_category=pain,
            urgency_level=urgency,
            decision_style=self._infer_decision_style(signal),
            preferred_channel=self._select_channel(signal),
            price_sensitivity=self._infer_price_sensitivity(signal),
            offer_tier=offer_config["tier"],
            stripe_price_id=os.getenv(offer_config["price_env"], ""),
            persona_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Generate copy with GPT-4o
        copy = self._generate_copy(persona)
        persona.headline    = copy.get("headline", "")
        persona.subheadline = copy.get("subheadline", "")
        persona.cta_text    = copy.get("cta", "Get Started")

        return persona

    def _infer_decision_style(self, signal: dict) -> str:
        signal_type = signal.get("signal_type", "")
        if signal_type in ["funding_round", "new_hire_executive"]:
            return "analytical"
        if signal_type in ["negative_review_competitor"]:
            return "emotional"
        if signal_type in ["irs_ein_filing", "domain_registered"]:
            return "authority"
        return "social_proof"

    def _select_channel(self, signal: dict) -> str:
        if signal.get("contact_phone"):
            return "sms"
        if signal.get("contact_email"):
            return "email"
        return "ads"

    def _infer_price_sensitivity(self, signal: dict) -> str:
        if signal.get("signal_type") == "funding_round":
            return "premium_buyer"
        if signal.get("signal_type") in ["irs_ein_filing", "domain_registered"]:
            return "price_sensitive"
        return "value_buyer"

    def _generate_copy(self, persona: Persona) -> dict:
        """GPT-4o generates hyper-personalized offer copy per persona."""
        prompt = f"""
You are a world-class direct response copywriter.
Write offer copy for a {persona.vertical} business called "{persona.company_name}".

Context:
- Pain category: {persona.pain_category}
- Urgency: {persona.urgency_level}
- Decision style: {persona.decision_style}
- Price sensitivity: {persona.price_sensitivity}
- Offer tier: {persona.offer_tier}

The product being sold is: Garcar AI — an autonomous business operations and revenue system for {persona.vertical} companies.

Return a JSON object with exactly these keys:
- "headline": (max 12 words, punchy, specific to their pain)
- "subheadline": (max 25 words, expand the value proposition)
- "cta": (max 5 words, action-oriented)

Do NOT be generic. Reference their specific industry pain. Be bold."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.85,
                max_tokens=200,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"GPT copy generation failed: {e}")
            return {
                "headline": f"Stop Losing Jobs to Slower {persona.vertical.title()} Companies",
                "subheadline": "Garcar AI automates your operations so you can focus on winning more contracts.",
                "cta": "Claim Your Edge Now"
            }
