"""Autonomous Revenue Loop — Garcar Enterprise
The closed-loop revenue engine:
  ACQUIRE → QUALIFY → CONVERT → FULFILL → COMPOUND → REINVEST

Each phase is an async stage. The loop never stops. Revenue compounds
automatically: a configurable percentage of every settlement is re-invested
into lead acquisition and ad spend.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("revenue_loop")
STATE_PATH = Path("revenue_loop_state.json")


@dataclass
class RevenueEvent:
    event_id: str
    phase: str          # acquire|qualify|convert|fulfill|compound|reinvest
    amount: float
    source: str
    ts: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)


class AutonomousRevenueLoop:
    """Production revenue loop with compounding and reinvestment."""

    # Tunable parameters
    REINVEST_RATIO = 0.20        # 20% of revenue re-invested into acquisition
    COMPOUND_INTERVAL = 3600     # compound every hour
    LEAD_VALUE_USD = 45.0        # average lead-to-close value
    CONVERSION_RATE = 0.12       # 12% close rate
    AFFILIATE_CUT = 0.08         # 8% to affiliate

    def __init__(self, stripe_client=None, nwu=None, rhns=None):
        self.stripe = stripe_client
        self.nwu = nwu
        self.rhns = rhns
        self._total_revenue = 0.0
        self._total_reinvested = 0.0
        self._cycle_count = 0
        self._events: List[RevenueEvent] = []
        self._running = False
        self._load_state()

    # ──────────────────────────────────────────
    # Phase 1 — ACQUIRE
    # ──────────────────────────────────────────

    async def acquire(self, leads: List[Dict]) -> List[Dict]:
        """Score and enrich incoming leads."""
        qualified = []
        for lead in leads:
            score = self._score_lead(lead)
            lead["score"] = score
            lead["qualified"] = score >= 0.5
            if self.nwu:
                token = self.nwu.mint("revenue_loop", "lead", lead)
                lead["nwu_token"] = token.token_id
            if lead["qualified"]:
                qualified.append(lead)
        log.info(f"Acquire: {len(leads)} leads → {len(qualified)} qualified")
        await self._record("acquire", len(qualified) * self.LEAD_VALUE_USD * self.CONVERSION_RATE, "lead_pipeline")
        return qualified

    def _score_lead(self, lead: Dict) -> float:
        score = 0.5
        if lead.get("email"):
            score += 0.15
        if lead.get("phone"):
            score += 0.10
        if lead.get("company"):
            score += 0.10
        if lead.get("budget", 0) > 500:
            score += 0.15
        return min(score, 1.0)

    # ──────────────────────────────────────────
    # Phase 2 — QUALIFY (LLM-powered in production)
    # ──────────────────────────────────────────

    async def qualify(self, leads: List[Dict]) -> List[Dict]:
        hot = [l for l in leads if l.get("score", 0) >= 0.70]
        warm = [l for l in leads if 0.50 <= l.get("score", 0) < 0.70]
        log.info(f"Qualify: {len(hot)} hot, {len(warm)} warm")
        return hot + warm

    # ──────────────────────────────────────────
    # Phase 3 — CONVERT
    # ──────────────────────────────────────────

    async def convert(self, leads: List[Dict]) -> float:
        """Simulate conversion. In production: trigger Stripe checkout links."""
        converted = [l for l in leads
                     if (l.get("score", 0) * self.CONVERSION_RATE) > 0.05]
        revenue = len(converted) * self.LEAD_VALUE_USD
        self._total_revenue += revenue
        await self._record("convert", revenue, "stripe_checkout")
        log.info(f"Convert: {len(converted)} converted → ${revenue:.2f}")
        return revenue

    # ──────────────────────────────────────────
    # Phase 4 — FULFILL
    # ──────────────────────────────────────────

    async def fulfill(self, revenue: float) -> float:
        """Deduct affiliate cuts and fulfillment costs."""
        affiliate_payout = revenue * self.AFFILIATE_CUT
        net = revenue - affiliate_payout
        await self._record("fulfill", net, "net_revenue")
        log.info(f"Fulfill: net=${net:.2f} (affiliate=${affiliate_payout:.2f})")
        return net

    # ──────────────────────────────────────────
    # Phase 5 — COMPOUND
    # ──────────────────────────────────────────

    async def compound(self, net: float) -> float:
        """Apply compound interest model to retained earnings."""
        compound_rate = 0.001  # 0.1% per cycle (configurable)
        gain = net * compound_rate
        self._total_revenue += gain
        await self._record("compound", gain, "compounding")
        log.info(f"Compound: gain=${gain:.4f}")
        return net + gain

    # ──────────────────────────────────────────
    # Phase 6 — REINVEST
    # ──────────────────────────────────────────

    async def reinvest(self, net: float) -> float:
        reinvest_amount = net * self.REINVEST_RATIO
        self._total_reinvested += reinvest_amount
        retained = net - reinvest_amount
        await self._record("reinvest", reinvest_amount, "ad_spend")
        log.info(f"Reinvest: ${reinvest_amount:.2f} → acquisition, ${retained:.2f} retained")
        return retained

    # ──────────────────────────────────────────
    # Full cycle
    # ──────────────────────────────────────────

    async def run_cycle(self, raw_leads: List[Dict]) -> Dict:
        self._cycle_count += 1
        t0 = time.time()
        log.info(f"Revenue cycle #{self._cycle_count} starting ({len(raw_leads)} leads)")
        acquired = await self.acquire(raw_leads)
        qualified = await self.qualify(acquired)
        gross = await self.convert(qualified)
        net = await self.fulfill(gross)
        compounded = await self.compound(net)
        retained = await self.reinvest(compounded)
        duration = time.time() - t0
        result = {
            "cycle": self._cycle_count,
            "duration_s": round(duration, 3),
            "leads_in": len(raw_leads),
            "qualified": len(qualified),
            "gross_revenue": round(gross, 4),
            "net_retained": round(retained, 4),
            "total_revenue": round(self._total_revenue, 4),
            "total_reinvested": round(self._total_reinvested, 4)
        }
        self._save_state()
        if self.rhns:
            await self.rhns._emit("revenue.cycle", result)
        log.info(f"Cycle #{self._cycle_count} complete: gross=${gross:.2f}, retained=${retained:.2f}")
        return result

    async def run(self, lead_source_fn, interval: int = 60):
        """Infinite revenue loop. lead_source_fn() must return List[Dict]."""
        self._running = True
        log.info("Autonomous revenue loop started")
        while self._running:
            try:
                leads = await lead_source_fn() if asyncio.iscoroutinefunction(lead_source_fn) \
                    else lead_source_fn()
                await self.run_cycle(leads)
            except Exception as e:
                log.error(f"Revenue loop error: {e}")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    async def _record(self, phase: str, amount: float, source: str):
        ev = RevenueEvent(event_id=f"{phase}-{int(time.time())}",
                          phase=phase, amount=amount, source=source)
        self._events.append(ev)
        if len(self._events) > 10000:
            self._events = self._events[-5000:]

    def _save_state(self):
        state = {
            "total_revenue": self._total_revenue,
            "total_reinvested": self._total_reinvested,
            "cycle_count": self._cycle_count,
            "events": [asdict(e) for e in self._events[-100:]]
        }
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        if not STATE_PATH.exists():
            return
        try:
            with open(STATE_PATH) as f:
                s = json.load(f)
            self._total_revenue = s.get("total_revenue", 0.0)
            self._total_reinvested = s.get("total_reinvested", 0.0)
            self._cycle_count = s.get("cycle_count", 0)
        except Exception:
            pass

    @property
    def summary(self) -> Dict:
        return {
            "total_revenue": round(self._total_revenue, 4),
            "total_reinvested": round(self._total_reinvested, 4),
            "cycles": self._cycle_count
        }
