"""Domain Agent Tests"""
import asyncio
import pytest
from services.healthcare_agent import HealthcareAgent
from services.legal_agent import LegalAgent
from services.contractor_agent import ContractorAgent


def make_task(cap, payload=None):
    return {"task_id": f"T-{cap}", "capability": cap, "payload": payload or {}}


@pytest.mark.asyncio
async def test_healthcare_billing():
    agent = HealthcareAgent()
    result = await agent.run_task(make_task("billing", {"visit_type": "new_patient"}))
    assert result.success
    assert result.revenue_impact == 250.0


@pytest.mark.asyncio
async def test_healthcare_compliance_clean():
    agent = HealthcareAgent()
    result = await agent.run_task(make_task("compliance", {"note": "patient recovered"}))
    assert result.success
    assert result.output["compliant"] is True


@pytest.mark.asyncio
async def test_legal_contract_review():
    agent = LegalAgent()
    result = await agent.run_task(make_task(
        "contract_review",
        {"text": "This contract includes arbitration and indemnify clauses."}
    ))
    assert result.success
    assert "arbitration" in result.output["risk_flags"]


@pytest.mark.asyncio
async def test_contractor_estimating():
    agent = ContractorAgent()
    result = await agent.run_task(make_task(
        "estimating", {"job": {"sqft": 2000, "rate_per_sqft": 9.0}}
    ))
    assert result.success
    assert result.output["total"] == 18000.0
