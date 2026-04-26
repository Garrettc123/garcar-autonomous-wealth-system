"""
Phase 2 — Policy-Compiled Action Gateway
Sole interface to all external systems.
Every call generates a signed policy receipt.

Usage:
    gateway = ActionGateway()
    receipt = await gateway.stripe_charge(amount_usd=99.0, customer_id="cus_xxx",
                                          justification="SaaS subscription",
                                          agent_id="revenue_agent")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from constitution.constitution_kernel import KERNEL, ConstitutionViolation, Verdict

logger = logging.getLogger("garcar.gateway")


# ---------------------------------------------------------------------------
# Policy Receipt
# ---------------------------------------------------------------------------

@dataclass
class PolicyReceipt:
    receipt_id:   str
    action_type:  str
    agent_id:     str
    params:       Dict[str, Any]
    verdict:      str
    receipt_hash: str
    timestamp:    float
    response:     Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Action Gateway
# ---------------------------------------------------------------------------

class ActionGateway:
    """
    Centralised gateway for all external system calls.
    Every action:
      1. Passes through ConstitutionKernel.enforce()
      2. Executes only if approved
      3. Emits a signed PolicyReceipt
    """

    def __init__(
        self,
        stripe_secret: str = "",
        github_token:  str = "",
        zapier_token:  str = "",
    ) -> None:
        self._stripe_secret = stripe_secret
        self._github_token  = github_token
        self._zapier_token  = zapier_token

    # ------------------------------------------------------------------
    # Internal: run critique + execute
    # ------------------------------------------------------------------

    async def _execute(
        self,
        action_type: str,
        agent_id:    str,
        params:      Dict[str, Any],
        executor:    Any,  # async callable or None (for dry-run)
    ) -> PolicyReceipt:
        action = {
            "action_id":   str(uuid.uuid4()),
            "action_type": action_type,
            "agent_id":    agent_id,
            "params":      params,
        }

        # Constitution gate
        critique = KERNEL.enforce(action)   # raises ConstitutionViolation if blocked

        # Execute
        response: Optional[Dict[str, Any]] = None
        if executor is not None:
            try:
                response = await executor(params)
            except Exception as exc:  # noqa: BLE001
                logger.error("Gateway executor error: %s", exc)
                response = {"error": str(exc)}

        # Build receipt
        receipt_payload = json.dumps(
            {
                "action_id":   action["action_id"],
                "action_type": action_type,
                "agent_id":    agent_id,
                "verdict":     critique.verdict.name,
                "ts":          time.time(),
            },
            sort_keys=True,
        )
        receipt_hash = hashlib.sha256(receipt_payload.encode()).hexdigest()

        receipt = PolicyReceipt(
            receipt_id=   action["action_id"],
            action_type=  action_type,
            agent_id=     agent_id,
            params=       params,
            verdict=      critique.verdict.name,
            receipt_hash= receipt_hash,
            timestamp=    time.time(),
            response=     response,
        )

        logger.info(
            "PolicyReceipt | type=%s agent=%s verdict=%s hash=%s",
            action_type, agent_id, critique.verdict.name, receipt_hash,
        )
        return receipt

    # ------------------------------------------------------------------
    # Stripe
    # ------------------------------------------------------------------

    async def stripe_charge(
        self,
        amount_usd:         float,
        customer_id:        str,
        agent_id:           str,
        justification:      str,
        operator_approved:  bool = False,
    ) -> PolicyReceipt:
        async def _exec(p: Dict) -> Dict:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.stripe.com/v1/payment_intents",
                    auth=(self._stripe_secret, ""),
                    data={
                        "amount":   int(p["amount_usd"] * 100),
                        "currency": "usd",
                        "customer": p["customer_id"],
                        "automatic_payment_methods[enabled]": "true",
                    },
                )
                return resp.json()

        return await self._execute(
            action_type = "stripe_charge",
            agent_id    = agent_id,
            params      = {
                "amount_usd":        amount_usd,
                "customer_id":       customer_id,
                "justification":     justification,
                "operator_approved": operator_approved,
            },
            executor = _exec,
        )

    # ------------------------------------------------------------------
    # GitHub Actions dispatch
    # ------------------------------------------------------------------

    async def github_dispatch(
        self,
        workflow_id: str,
        repo:        str,
        agent_id:    str,
        inputs:      Optional[Dict[str, Any]] = None,
    ) -> PolicyReceipt:
        async def _exec(p: Dict) -> Dict:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{p['repo']}/actions/workflows/{p['workflow_id']}/dispatches",
                    headers={
                        "Authorization": f"Bearer {self._github_token}",
                        "Accept":        "application/vnd.github+json",
                    },
                    json={"ref": "main", "inputs": p.get("inputs") or {}},
                )
                return {"status_code": resp.status_code}

        return await self._execute(
            action_type = "github_dispatch",
            agent_id    = agent_id,
            params      = {"workflow_id": workflow_id, "repo": repo,
                           "inputs": inputs or {}},
            executor = _exec,
        )

    # ------------------------------------------------------------------
    # Zapier webhook
    # ------------------------------------------------------------------

    async def zapier_trigger(
        self,
        hook_url:           str,
        payload:            Dict[str, Any],
        agent_id:           str,
        signature_verified: bool = False,
    ) -> PolicyReceipt:
        async def _exec(p: Dict) -> Dict:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    p["hook_url"],
                    headers={"Authorization": f"Bearer {self._zapier_token}"},
                    json=p["payload"],
                )
                return {"status_code": resp.status_code}

        return await self._execute(
            action_type = "zapier_trigger",
            agent_id    = agent_id,
            params      = {
                "hook_url":           hook_url,
                "payload":            payload,
                "signature_verified": signature_verified,
            },
            executor = _exec,
        )
