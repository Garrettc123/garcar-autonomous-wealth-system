"""
Phase 1 — Constitution Kernel
Immutable prohibitions + pre-execution critique pass for every agent action.
Wire into FastAPI via ConstitutionMiddleware.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Final, FrozenSet

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


# ── Verdict ──────────────────────────────────────────────────────────────────
class Verdict(str, Enum):
    ALLOW   = "ALLOW"
    DENY    = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CritiqueResult:
    verdict:     Verdict
    rule_hit:    str | None
    critique:    str
    action_hash: str
    timestamp:   float = field(default_factory=time.time)
    receipt_id:  str   = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "receipt_id":  self.receipt_id,
            "verdict":     self.verdict.value,
            "rule_hit":    self.rule_hit,
            "critique":    self.critique,
            "action_hash": self.action_hash,
            "timestamp":   self.timestamp,
        }


# ── Immutable Prohibition Set ─────────────────────────────────────────────────
class ConstitutionKernel:
    """
    Immutable core.  Rules are frozen at construction time.
    No runtime mutation is permitted — any attempt raises TypeError.
    """

    # Hard prohibitions: any action matching ANY of these is DENIED immediately.
    _PROHIBITIONS: Final[FrozenSet[str]] = frozenset({
        # Financial safety
        "charge_without_consent",
        "refund_reversal_fraud",
        "unauthorized_payout",
        "bulk_charge_all_customers",
        "delete_payment_method",
        # Data safety
        "exfiltrate_pii",
        "bulk_export_customer_data",
        "drop_database",
        "wipe_ledger",
        # Infrastructure
        "disable_circuit_breaker",
        "bypass_rate_limit",
        "self_replicate_without_approval",
        "modify_constitution",           # Self-protection
        "disable_safety_visor",
        # Legal / compliance
        "send_spam_blast",
        "violate_gdpr_deletion",
        "store_card_plaintext",
    })

    # Escalation triggers: suspicious but not immediately illegal
    _ESCALATION_TRIGGERS: Final[FrozenSet[str]] = frozenset({
        "large_batch_payment",           # >$1k aggregate in one action
        "new_external_webhook",
        "deploy_to_production",
        "schema_migration",
        "modify_agent_policy",
        "access_kms_key",
    })

    # Critique heuristics: patterns the kernel looks for in action payloads
    _CRITIQUE_RULES: Final[tuple[tuple[str, str], ...]] = (
        ("amount",       "Action involves monetary value — verify consent and idempotency key"),
        ("email",        "PII in payload — confirm data minimisation and retention policy"),
        ("webhook_url",  "External egress endpoint — verify domain allowlist"),
        ("api_key",      "Credential present in payload — must be resolved via Secrets Manager"),
        ("delete",       "Destructive operation — confirm soft-delete and audit trail"),
        ("admin",        "Elevated privilege scope — require dual authorisation"),
    )

    def __init__(self) -> None:
        # Seal: prevent any attribute mutation after init
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:  # type: ignore[override]
        if getattr(self, "_sealed", False):
            raise TypeError("ConstitutionKernel is immutable after initialisation")
        super().__setattr__(name, value)

    # ── Public API ────────────────────────────────────────────────────────────

    def evaluate(self, action_type: str, payload: dict[str, Any]) -> CritiqueResult:
        """
        Pre-execution critique pass.
        Returns a CritiqueResult with verdict ALLOW / DENY / ESCALATE.
        """
        action_hash = self._hash_action(action_type, payload)
        action_lower = action_type.lower()

        # 1. Hard prohibition check
        if action_lower in self._PROHIBITIONS:
            return CritiqueResult(
                verdict=Verdict.DENY,
                rule_hit=action_lower,
                critique=f"PROHIBITED: '{action_type}' is constitutionally forbidden. No override permitted.",
                action_hash=action_hash,
            )

        # 2. Escalation trigger check
        if action_lower in self._ESCALATION_TRIGGERS:
            return CritiqueResult(
                verdict=Verdict.ESCALATE,
                rule_hit=action_lower,
                critique=f"ESCALATION: '{action_type}' requires human approval before execution.",
                action_hash=action_hash,
            )

        # 3. Payload critique heuristics
        payload_str = json.dumps(payload, default=str).lower()
        for keyword, advice in self._CRITIQUE_RULES:
            if keyword in payload_str:
                return CritiqueResult(
                    verdict=Verdict.ALLOW,
                    rule_hit=keyword,
                    critique=f"ADVISORY [{keyword}]: {advice}",
                    action_hash=action_hash,
                )

        # 4. Clean pass
        return CritiqueResult(
            verdict=Verdict.ALLOW,
            rule_hit=None,
            critique="Constitution pass: no violations detected.",
            action_hash=action_hash,
        )

    def audit_log_entry(self, result: CritiqueResult, agent_id: str) -> dict:
        entry = result.to_dict()
        entry["agent_id"] = agent_id
        return entry

    @staticmethod
    def _hash_action(action_type: str, payload: dict) -> str:
        raw = json.dumps({"action": action_type, "payload": payload}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── FastAPI Middleware ────────────────────────────────────────────────────────

class ConstitutionMiddleware(BaseHTTPMiddleware):
    """
    Wires the ConstitutionKernel into every FastAPI request as a middleware layer.
    Agent action routes must include X-Agent-Action and X-Agent-ID headers.
    DENY → 403.  ESCALATE → 202 (queued for human approval).
    """

    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app: ASGIApp, kernel: ConstitutionKernel | None = None) -> None:
        super().__init__(app)
        self._kernel = kernel or ConstitutionKernel()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        action_type = request.headers.get("X-Agent-Action", "unknown")
        agent_id    = request.headers.get("X-Agent-ID",     "unknown")

        # Best-effort payload extraction (don't block on body parse errors)
        try:
            body = await request.body()
            payload: dict = json.loads(body) if body else {}
        except Exception:
            payload = {}

        result = self._kernel.evaluate(action_type, payload)

        # Attach receipt to downstream context
        request.state.constitution_receipt = result

        if result.verdict == Verdict.DENY:
            return Response(
                content=json.dumps({"error": "Constitutional violation", "detail": result.critique, "receipt_id": result.receipt_id}),
                status_code=403,
                media_type="application/json",
            )

        if result.verdict == Verdict.ESCALATE:
            # Queue for human approval — respond 202 immediately
            return Response(
                content=json.dumps({"status": "ESCALATED", "detail": result.critique, "receipt_id": result.receipt_id}),
                status_code=202,
                media_type="application/json",
            )

        response = await call_next(request)
        response.headers["X-Constitution-Receipt"] = result.receipt_id
        response.headers["X-Constitution-Verdict"]  = result.verdict.value
        return response


# ── Bootstrap helper ─────────────────────────────────────────────────────────

def mount_constitution(app: FastAPI) -> ConstitutionKernel:
    """Call once at app startup: app = FastAPI(); mount_constitution(app)"""
    kernel = ConstitutionKernel()
    app.add_middleware(ConstitutionMiddleware, kernel=kernel)
    return kernel
