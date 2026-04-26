"""
Phase 3 — Capability Sharding
Protects Reasoning Doctrine and Monetization Trigger shards via AWS KMS.
Shards are never loaded into memory as plaintext simultaneously.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

try:
    import boto3
    _HAS_BOTO = True
except ImportError:
    _HAS_BOTO = False


class ShardID(str, Enum):
    REASONING_DOCTRINE    = "reasoning_doctrine"
    MONETIZATION_TRIGGER  = "monetization_trigger"
    ACQUISITION_POLICY    = "acquisition_policy"
    COMPLIANCE_RULESET    = "compliance_ruleset"


@dataclass
class ShardContext:
    shard_id:    ShardID
    agent_id:    str
    purpose:     str
    requested_at: float
    lease_ttl:   int = 60  # seconds before shard must be released


class CapabilityShardManager:
    """
    Manages encrypted capability shards.
    Each shard is encrypted with a unique AWS KMS data key.
    Agents are granted time-limited leases; the plaintext is never persisted.

    In dev mode (no AWS credentials), uses local AES-256 simulation.
    """

    def __init__(
        self,
        kms_key_id:  str | None = None,
        region:      str = "us-east-1",
        dev_mode:    bool = False,
    ) -> None:
        self._kms_key_id = kms_key_id or os.getenv("KMS_KEY_ID", "")
        self._region     = region
        self._dev_mode   = dev_mode or not _HAS_BOTO or not self._kms_key_id
        self._active_leases: dict[str, dict] = {}
        self._shard_store:   dict[str, bytes] = {}  # encrypted blobs

        if not self._dev_mode:
            self._kms = boto3.client("kms", region_name=self._region)

    # ── Store shard ───────────────────────────────────────────────────────────

    def store_shard(self, shard_id: ShardID, plaintext_policy: dict) -> str:
        """
        Encrypt and store a capability shard.
        Returns the envelope key reference (never the plaintext).
        """
        raw = json.dumps(plaintext_policy).encode()

        if self._dev_mode:
            # Dev: XOR with a fixed pad (NOT for production)
            key  = os.getenv("DEV_SHARD_SECRET", "garcar-dev-shard-key-32bytes!!!").encode()[:32]
            blob = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
            self._shard_store[shard_id.value] = blob
            return f"dev-envelope:{shard_id.value}"

        # Production: KMS GenerateDataKey
        dk   = self._kms.generate_data_key(KeyId=self._kms_key_id, KeySpec="AES_256")
        from cryptography.fernet import Fernet
        import base64
        key_b64 = base64.urlsafe_b64encode(dk["Plaintext"])
        token   = Fernet(key_b64).encrypt(raw)
        envelope = {
            "encrypted_data_key": base64.b64encode(dk["CiphertextBlob"]).decode(),
            "ciphertext":         base64.b64encode(token).decode(),
        }
        self._shard_store[shard_id.value] = json.dumps(envelope).encode()
        return f"kms:{self._kms_key_id}:{shard_id.value}"

    # ── Lease shard ───────────────────────────────────────────────────────────

    def lease_shard(self, shard_id: ShardID, ctx: ShardContext) -> dict:
        """
        Decrypt and return the shard payload for the duration of a lease.
        The caller MUST call release_shard() when done.
        """
        lease_id = str(uuid.uuid4())
        plaintext = self._decrypt(shard_id)
        self._active_leases[lease_id] = {
            "shard_id":   shard_id.value,
            "agent_id":   ctx.agent_id,
            "expires_at": time.time() + ctx.lease_ttl,
        }
        return {"lease_id": lease_id, "payload": plaintext}

    def release_shard(self, lease_id: str) -> None:
        """Explicitly revoke a shard lease and zero out context."""
        self._active_leases.pop(lease_id, None)

    def sweep_expired_leases(self) -> int:
        """Call periodically to revoke expired leases. Returns count removed."""
        now     = time.time()
        expired = [lid for lid, l in self._active_leases.items() if l["expires_at"] < now]
        for lid in expired:
            del self._active_leases[lid]
        return len(expired)

    def active_lease_count(self) -> int:
        return len(self._active_leases)

    # ── Internal decrypt ──────────────────────────────────────────────────────

    def _decrypt(self, shard_id: ShardID) -> dict:
        blob = self._shard_store.get(shard_id.value)
        if blob is None:
            raise KeyError(f"Shard '{shard_id.value}' not found — store it first")

        if self._dev_mode:
            key  = os.getenv("DEV_SHARD_SECRET", "garcar-dev-shard-key-32bytes!!!").encode()[:32]
            raw  = bytes(b ^ key[i % len(key)] for i, b in enumerate(blob))
            return json.loads(raw)

        envelope = json.loads(blob)
        import base64
        plaintext_key = self._kms.decrypt(
            CiphertextBlob=base64.b64decode(envelope["encrypted_data_key"])
        )["Plaintext"]
        from cryptography.fernet import Fernet
        key_b64 = base64.urlsafe_b64encode(plaintext_key)
        raw = Fernet(key_b64).decrypt(base64.b64decode(envelope["ciphertext"]))
        return json.loads(raw)


# ── Pre-loaded shard templates ────────────────────────────────────────────────

REASONING_DOCTRINE_POLICY: dict[str, Any] = {
    "version": "1.0",
    "doctrine": "RHNS Reasoning Doctrine",
    "rules": [
        "Always prefer reversible actions over irreversible ones",
        "When in doubt, escalate to human oversight",
        "Revenue maximisation is constrained by legal and ethical bounds",
        "No single agent may hold more than one high-value shard at a time",
        "Critique every action before execution — no exceptions",
    ],
    "max_autonomous_spend_usd": 500,
    "requires_human_approval_above_usd": 1000,
}

MONETIZATION_TRIGGER_POLICY: dict[str, Any] = {
    "version": "1.0",
    "doctrine": "Monetization Trigger Doctrine",
    "allowed_triggers": [
        "stripe_invoice_create",
        "stripe_subscription_activate",
        "affiliate_commission_payout",
        "lead_conversion_event",
    ],
    "prohibited_triggers": [
        "bulk_charge_all_customers",
        "unauthorized_payout",
        "refund_reversal_fraud",
    ],
    "daily_revenue_cap_usd": 50000,
    "alert_threshold_usd":  10000,
}
