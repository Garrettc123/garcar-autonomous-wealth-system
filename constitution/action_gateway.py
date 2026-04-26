"""
Phase 2 — Policy-Compiled Action Gateway
Sole interface to all external systems (Stripe, GitHub Actions, Zapier).
Generates a signed policy receipt for every action.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from .constitution_kernel import ConstitutionKernel, Verdict


# ── Policy Receipt ────────────────────────────────────────────────────────────
@dataclass
class PolicyReceipt:
    receipt_id:    str
    action_type:   str
    target_system: str
    verdict:       str
    critique:      str
    payload_hash:  str
    executed_at:   float
    response_code: int | None   = None
    response_body: str | None   = None
    signature:     str | None   = None

    def sign(self, secret: str) -> "PolicyReceipt":
        raw = f"{self.receipt_id}:{self.action_type}:{self.payload_hash}:{self.executed_at}"
        self.signature = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        return self

    def to_dict(self) -> dict:
        return self.__dict__


# ── Allowed External Systems ──────────────────────────────────────────────────
class ExternalSystem(str, Enum):
    STRIPE         = "stripe"
    GITHUB_ACTIONS = "github_actions"
    ZAPIER         = "zapier"


# ── Gateway ───────────────────────────────────────────────────────────────────
class ActionGateway:
    """
    Every call to an external system must flow through this gateway.
    Calls are:
      1. Constitutionally evaluated (DENY → blocked)
      2. Executed if ALLOW
      3. Receipted with a signed policy record
    """

    _BASE_URLS: dict[str, str] = {
        ExternalSystem.STRIPE:         "https://api.stripe.com/v1",
        ExternalSystem.GITHUB_ACTIONS: "https://api.github.com/repos",
        ExternalSystem.ZAPIER:         "https://hooks.zapier.com/hooks/catch",
    }

    def __init__(
        self,
        kernel:         ConstitutionKernel | None = None,
        receipt_secret: str | None = None,
        dry_run:        bool = False,
    ) -> None:
        self._kernel  = kernel or ConstitutionKernel()
        self._secret  = receipt_secret or os.getenv("GATEWAY_RECEIPT_SECRET", "garcar-dev-secret")
        self._dry_run = dry_run
        self._receipts: list[PolicyReceipt] = []

    # ── Public dispatch ───────────────────────────────────────────────────────

    async def dispatch(
        self,
        system:      ExternalSystem | str,
        action_type: str,
        endpoint:    str,
        payload:     dict[str, Any],
        method:      str = "POST",
        headers:     dict[str, str] | None = None,
        agent_id:    str = "system",
    ) -> PolicyReceipt:
        critique_result = self._kernel.evaluate(action_type, payload)

        receipt = PolicyReceipt(
            receipt_id=str(uuid.uuid4()),
            action_type=action_type,
            target_system=str(system),
            verdict=critique_result.verdict.value,
            critique=critique_result.critique,
            payload_hash=critique_result.action_hash,
            executed_at=time.time(),
        )

        if critique_result.verdict == Verdict.DENY:
            receipt.response_code = 403
            receipt.response_body = "Blocked by Constitution Kernel"
            self._store_receipt(receipt)
            raise PermissionError(f"Gateway DENY: {critique_result.critique}")

        if critique_result.verdict == Verdict.ESCALATE:
            receipt.response_code = 202
            receipt.response_body = "Queued for human approval"
            self._store_receipt(receipt)
            return receipt

        if self._dry_run:
            receipt.response_code = 200
            receipt.response_body = "DRY_RUN: not executed"
            self._store_receipt(receipt)
            return receipt

        # Execute
        base = self._BASE_URLS.get(str(system), "")
        url  = f"{base}{endpoint}" if base else endpoint
        hdrs = headers or {}
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["X-Gateway-Receipt"] = receipt.receipt_id

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, json=payload, headers=hdrs)
            receipt.response_code = resp.status_code
            receipt.response_body = resp.text[:500]

        receipt.sign(self._secret)
        self._store_receipt(receipt)
        return receipt

    # ── Stripe convenience ────────────────────────────────────────────────────

    async def stripe(
        self,
        action_type: str,
        endpoint: str,
        payload: dict,
        agent_id: str = "revenue_agent",
    ) -> PolicyReceipt:
        api_key = os.getenv("STRIPE_SECRET_KEY", "")
        return await self.dispatch(
            system=ExternalSystem.STRIPE,
            action_type=action_type,
            endpoint=endpoint,
            payload=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            agent_id=agent_id,
        )

    # ── GitHub Actions convenience ────────────────────────────────────────────

    async def github_dispatch(
        self,
        repo: str,
        workflow: str,
        ref: str = "main",
        inputs: dict | None = None,
        agent_id: str = "ci_agent",
    ) -> PolicyReceipt:
        token = os.getenv("GITHUB_TOKEN", "")
        return await self.dispatch(
            system=ExternalSystem.GITHUB_ACTIONS,
            action_type="deploy_to_production",
            endpoint=f"/{repo}/actions/workflows/{workflow}/dispatches",
            payload={"ref": ref, "inputs": inputs or {}},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            agent_id=agent_id,
        )

    # ── Zapier convenience ────────────────────────────────────────────────────

    async def zapier(
        self,
        hook_path: str,
        payload: dict,
        agent_id: str = "automation_agent",
    ) -> PolicyReceipt:
        return await self.dispatch(
            system=ExternalSystem.ZAPIER,
            action_type="zapier_webhook",
            endpoint=f"/{hook_path}",
            payload=payload,
            agent_id=agent_id,
        )

    # ── Receipt management ────────────────────────────────────────────────────

    def _store_receipt(self, receipt: PolicyReceipt) -> None:
        self._receipts.append(receipt)
        # Persist to disk (append-only audit log)
        log_path = os.getenv("RECEIPT_LOG_PATH", "/tmp/policy_receipts.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(receipt.to_dict()) + "\n")

    def get_receipts(self, limit: int = 100) -> list[dict]:
        return [r.to_dict() for r in self._receipts[-limit:]]
