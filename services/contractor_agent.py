"""Contractor Domain Agent — Garcar Enterprise
Handles: lead generation, estimating, scheduling, invoicing.
"""
from __future__ import annotations
import asyncio
import logging
import time
import random
from typing import Dict, List

from services.domain_agent_base import DomainAgentBase, TaskResult

log = logging.getLogger("contractor_agent")


class ContractorAgent(DomainAgentBase):

    def __init__(self, rhns=None, nwu=None):
        super().__init__("contractor-agent", "contractor", rhns=rhns, nwu=nwu)

    @property
    def capabilities(self) -> List[str]:
        return ["lead_gen", "estimating", "scheduling", "invoicing"]

    async def execute_task(self, task: Dict) -> TaskResult:
        cap = task.get("capability", "")
        handlers = {
            "lead_gen":   self._lead_gen,
            "estimating": self._estimating,
            "scheduling": self._scheduling,
            "invoicing":  self._invoicing,
        }
        handler = handlers.get(cap)
        if not handler:
            return TaskResult(task["task_id"], False, None, 0, error=f"unknown cap: {cap}")
        return await handler(task)

    async def _lead_gen(self, task: Dict) -> TaskResult:
        await asyncio.sleep(0.04)
        leads = [
            {"name": f"Prospect {i}", "type": random.choice(["residential", "commercial"]),
             "estimated_value": random.uniform(500, 15000)}
            for i in range(random.randint(3, 10))
        ]
        return TaskResult(task["task_id"], True, {"leads": leads}, 0,
                          revenue_impact=sum(l["estimated_value"] * 0.1 for l in leads))

    async def _estimating(self, task: Dict) -> TaskResult:
        job = task.get("payload", {}).get("job", {})
        sqft = job.get("sqft", 1000)
        rate = job.get("rate_per_sqft", 8.50)
        estimate = {"job_id": f"JOB-{int(time.time())}",
                    "sqft": sqft, "rate": rate,
                    "total": round(sqft * rate, 2),
                    "valid_days": 30}
        return TaskResult(task["task_id"], True, estimate, 0,
                          revenue_impact=estimate["total"] * 0.35)

    async def _scheduling(self, task: Dict) -> TaskResult:
        crew = task.get("payload", {}).get("crew_size", 3)
        schedule = {"job_id": f"JOB-{int(time.time())}",
                    "crew": crew, "start_date": task.get("payload", {}).get("start"),
                    "confirmed": True}
        return TaskResult(task["task_id"], True, schedule, 0, revenue_impact=50.0 * crew)

    async def _invoicing(self, task: Dict) -> TaskResult:
        amount = task.get("payload", {}).get("amount", 2500.0)
        invoice = {"invoice_id": f"CINV-{int(time.time())}",
                   "amount": amount, "due_days": 30, "status": "sent"}
        return TaskResult(task["task_id"], True, invoice, 0, revenue_impact=amount)
