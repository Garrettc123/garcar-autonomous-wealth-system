"""Legal Domain Agent — Garcar Enterprise
Handles: contract review, client intake, billing, court calendar sync.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List

from services.domain_agent_base import DomainAgentBase, TaskResult

log = logging.getLogger("legal_agent")


class LegalAgent(DomainAgentBase):

    BILLING_RATES = {"contract_review": 350.0, "intake": 200.0, "hearing_prep": 500.0}

    def __init__(self, rhns=None, nwu=None):
        super().__init__("legal-agent", "legal", rhns=rhns, nwu=nwu)

    @property
    def capabilities(self) -> List[str]:
        return ["contract_review", "intake", "billing", "court_calendar"]

    async def execute_task(self, task: Dict) -> TaskResult:
        cap = task.get("capability", "")
        handlers = {
            "contract_review": self._contract_review,
            "intake":          self._intake,
            "billing":         self._billing,
            "court_calendar":  self._court_calendar,
        }
        handler = handlers.get(cap)
        if not handler:
            return TaskResult(task["task_id"], False, None, 0, error=f"unknown cap: {cap}")
        return await handler(task)

    async def _contract_review(self, task: Dict) -> TaskResult:
        await asyncio.sleep(0.08)
        text = task.get("payload", {}).get("text", "")
        risk_flags = []
        for keyword in ["arbitration", "indemnify", "liability cap", "termination at will"]:
            if keyword.lower() in text.lower():
                risk_flags.append(keyword)
        return TaskResult(
            task["task_id"], True,
            {"risk_flags": risk_flags, "risk_level": "high" if len(risk_flags) > 2 else "low",
             "reviewed_at": time.time()},
            0, revenue_impact=self.BILLING_RATES["contract_review"]
        )

    async def _intake(self, task: Dict) -> TaskResult:
        await asyncio.sleep(0.03)
        client = task.get("payload", {}).get("client", {})
        return TaskResult(
            task["task_id"], True,
            {"case_id": f"CASE-{int(time.time())}", "client": client, "status": "open"},
            0, revenue_impact=self.BILLING_RATES["intake"]
        )

    async def _billing(self, task: Dict) -> TaskResult:
        hours = task.get("payload", {}).get("hours", 1.0)
        rate = task.get("payload", {}).get("hourly_rate", 300.0)
        amount = hours * rate
        return TaskResult(
            task["task_id"], True,
            {"invoice_id": f"LINV-{int(time.time())}", "amount": amount, "status": "sent"},
            0, revenue_impact=amount
        )

    async def _court_calendar(self, task: Dict) -> TaskResult:
        events = task.get("payload", {}).get("events", [])
        synced = [{"event": e, "calendar_id": f"CAL-{i}", "synced": True}
                  for i, e in enumerate(events)]
        return TaskResult(task["task_id"], True, {"synced": synced}, 0, revenue_impact=0.0)
