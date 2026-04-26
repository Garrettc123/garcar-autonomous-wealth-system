"""
Phase 1 — Constitution Kernel
Immutable prohibitions + pre-execution critique pass.
Wire into FastAPI via ConstitutionMiddleware.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Verdict(Enum):
    APPROVED   = auto()
    BLOCKED    = auto()
    ESCALATE   = auto()


class Severity(Enum):
    CRITICAL   = 0   # Absolute block — never override
    HIGH       = 1   # Block unless operator-approved
    MEDIUM     = 2   # Warn and log
    LOW        = 3   # Log only


# ---------------------------------------------------------------------------
# Immutable Prohibition Rule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Prohibition:
    """A single immutable rule in the constitution."""
    rule_id:     str
    severity:    Severity
    description: str
    # A pure function (action_dict) -> bool; True = violation detected
    matcher:     Callable[[Dict[str, Any]], bool] = field(compare=False, hash=False)


# ---------------------------------------------------------------------------
# Critique Result
# ---------------------------------------------------------------------------

@dataclass
class CritiqueResult:
    verdict:      Verdict
    action_id:    str
    agent_id:     str
    action_type:  str
    violations:   List[Dict[str, Any]]
    critique_text: str
    timestamp:    float
    receipt_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict":      self.verdict.name,
            "action_id":    self.action_id,
            "agent_id":     self.agent_id,
            "action_type":  self.action_type,
            "violations":   self.violations,
            "critique_text": self.critique_text,
            "timestamp":    self.timestamp,
            "receipt_hash": self.receipt_hash,
        }


# ---------------------------------------------------------------------------
# Constitution Kernel
# ---------------------------------------------------------------------------

class ConstitutionKernel:
    """
    Singleton constitutional runtime.
    All prohibitions are frozen at class definition time.
    No runtime mutation is permitted.
    """

    # ---- Hardcoded immutable prohibitions --------------------------------
    _PROHIBITIONS: Tuple[Prohibition, ...] = (
        # CRITICAL — absolute blocks
        Prohibition(
            rule_id="C-001",
            severity=Severity.CRITICAL,
            description="No direct credential exfiltration to external hosts",
            matcher=lambda a: (
                a.get("action_type") in {"http_request", "webhook", "email"}
                and any(k in str(a.get("payload", ""))
                        for k in ["SECRET", "API_KEY", "STRIPE_SECRET",
                                  "OPENAI_API_KEY", "AWS_SECRET"])
            ),
        ),
        Prohibition(
            rule_id="C-002",
            severity=Severity.CRITICAL,
            description="No autonomous deletion of production data stores",
            matcher=lambda a: (
                a.get("action_type") in {"db_write", "s3_delete", "redis_flush"}
                and a.get("params", {}).get("destructive") is True
                and not a.get("params", {}).get("operator_approved")
            ),
        ),
        Prohibition(
            rule_id="C-003",
            severity=Severity.CRITICAL,
            description="No financial disbursement above per-cycle threshold without approval",
            matcher=lambda a: (
                a.get("action_type") in {"stripe_charge", "stripe_transfer", "payout"}
                and float(a.get("params", {}).get("amount_usd", 0)) > 500.0
                and not a.get("params", {}).get("operator_approved")
            ),
        ),
        Prohibition(
            rule_id="C-004",
            severity=Severity.CRITICAL,
            description="No self-modification of constitutional files",
            matcher=lambda a: (
                a.get("action_type") in {"file_write", "github_push"}
                and "constitution" in str(a.get("params", {}).get("path", ""))
            ),
        ),
        # HIGH — block unless explicitly approved
        Prohibition(
            rule_id="H-001",
            severity=Severity.HIGH,
            description="No outbound email/SMS to >100 recipients per cycle without approval",
            matcher=lambda a: (
                a.get("action_type") in {"email_send", "sms_send"}
                and len(a.get("params", {}).get("recipients", [])) > 100
                and not a.get("params", {}).get("operator_approved")
            ),
        ),
        Prohibition(
            rule_id="H-002",
            severity=Severity.HIGH,
            description="No GitHub Actions workflow dispatch to non-whitelisted repos",
            matcher=lambda a: (
                a.get("action_type") == "github_dispatch"
                and a.get("params", {}).get("repo") not in {
                    "Garrettc123/garcar-autonomous-wealth-system"
                }
            ),
        ),
        Prohibition(
            rule_id="H-003",
            severity=Severity.HIGH,
            description="No Zapier webhook triggers with unverified payload signatures",
            matcher=lambda a: (
                a.get("action_type") == "zapier_trigger"
                and not a.get("params", {}).get("signature_verified")
            ),
        ),
        # MEDIUM — warn and log
        Prohibition(
            rule_id="M-001",
            severity=Severity.MEDIUM,
            description="Revenue actions should include a monetization justification",
            matcher=lambda a: (
                a.get("action_type") in {"stripe_charge", "create_invoice"}
                and not a.get("params", {}).get("justification")
            ),
        ),
    )

    def __init__(self) -> None:
        # Defensive: re-freeze tuple so subclasses can't inject rules
        object.__setattr__(self, "_prohibitions", self._PROHIBITIONS)

    # ------------------------------------------------------------------
    # Core critique pass
    # ------------------------------------------------------------------

    def critique(self, action: Dict[str, Any]) -> CritiqueResult:
        """
        Run the pre-execution critique pass.
        Returns a CritiqueResult — callers must check .verdict before executing.
        """
        action_id   = action.get("action_id", str(uuid.uuid4()))
        agent_id    = action.get("agent_id", "unknown")
        action_type = action.get("action_type", "unknown")

        violations:   List[Dict[str, Any]] = []
        blocked       = False
        escalate      = False
        critique_lines: List[str] = []

        for prohibition in self._prohibitions:
            try:
                triggered = prohibition.matcher(action)
            except Exception as exc:  # noqa: BLE001
                triggered = False
                critique_lines.append(
                    f"[WARN] Rule {prohibition.rule_id} eval error: {exc}"
                )

            if triggered:
                violations.append({
                    "rule_id":     prohibition.rule_id,
                    "severity":    prohibition.severity.name,
                    "description": prohibition.description,
                })
                critique_lines.append(
                    f"[{prohibition.severity.name}] Violation: {prohibition.description} "
                    f"(rule {prohibition.rule_id})"
                )
                if prohibition.severity == Severity.CRITICAL:
                    blocked = True
                elif prohibition.severity == Severity.HIGH:
                    blocked = True
                    escalate = True

        if not violations:
            critique_lines.append("[PASS] No constitutional violations detected.")

        verdict = (
            Verdict.BLOCKED   if blocked  else
            Verdict.ESCALATE  if escalate else
            Verdict.APPROVED
        )

        receipt_payload = json.dumps(
            {"action_id": action_id, "verdict": verdict.name,
             "violations": violations, "ts": time.time()},
            sort_keys=True
        )
        receipt_hash = hashlib.sha256(receipt_payload.encode()).hexdigest()

        return CritiqueResult(
            verdict       = verdict,
            action_id     = action_id,
            agent_id      = agent_id,
            action_type   = action_type,
            violations    = violations,
            critique_text = "\n".join(critique_lines),
            timestamp     = time.time(),
            receipt_hash  = receipt_hash,
        )

    # ------------------------------------------------------------------
    # Convenience guard — raises on block
    # ------------------------------------------------------------------

    def enforce(self, action: Dict[str, Any]) -> CritiqueResult:
        """Critique and raise ConstitutionViolation if blocked."""
        result = self.critique(action)
        if result.verdict == Verdict.BLOCKED:
            raise ConstitutionViolation(result)
        return result


class ConstitutionViolation(Exception):
    def __init__(self, result: CritiqueResult) -> None:
        self.result = result
        super().__init__(
            f"Constitutional block [{result.action_id}]: "
            f"{result.critique_text}"
        )


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

KERNEL = ConstitutionKernel()
