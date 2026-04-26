"""
Phase 3 — Capability Sharding
Splits high-value reasoning and monetization logic into
encrypted shards. Keys managed via AWS KMS.

Shards:
  SHARD_REASONING      — Reasoning Doctrine (core AI decision logic)
  SHARD_MONETIZATION   — Monetization Trigger (revenue firing rules)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

try:
    import boto3
    from botocore.exceptions import ClientError as BotoClientError
    BOTO_AVAILABLE = True
except ImportError:
    BOTO_AVAILABLE = False
    BotoClientError = Exception  # type: ignore

logger = logging.getLogger("garcar.sharding")


# ---------------------------------------------------------------------------
# Shard identifiers
# ---------------------------------------------------------------------------

class ShardID(str, Enum):
    REASONING     = "SHARD_REASONING"
    MONETIZATION  = "SHARD_MONETIZATION"


# ---------------------------------------------------------------------------
# Shard Descriptor
# ---------------------------------------------------------------------------

@dataclass
class ShardDescriptor:
    shard_id:         ShardID
    kms_key_alias:    str    # e.g. "alias/garcar-reasoning-shard"
    plaintext_doc:    str    # In prod, this is NEVER stored — only in memory at load time
    encrypted_blob:   Optional[bytes] = None
    loaded_at:        Optional[float] = None


# ---------------------------------------------------------------------------
# Shard Registry
# ---------------------------------------------------------------------------

SHARD_REGISTRY: Dict[ShardID, ShardDescriptor] = {
    ShardID.REASONING: ShardDescriptor(
        shard_id=      ShardID.REASONING,
        kms_key_alias= os.getenv("KMS_KEY_REASONING", "alias/garcar-reasoning-shard"),
        plaintext_doc= json.dumps({
            "doctrine": "reasoning_v1",
            "rules": [
                "Prefer minimum-footprint actions",
                "Decompose goals before acting",
                "Validate assumption chain before external call",
                "Flag irreversible actions for human review",
            ],
        }),
    ),
    ShardID.MONETIZATION: ShardDescriptor(
        shard_id=      ShardID.MONETIZATION,
        kms_key_alias= os.getenv("KMS_KEY_MONETIZATION", "alias/garcar-monetization-shard"),
        plaintext_doc= json.dumps({
            "doctrine": "monetization_v1",
            "triggers": [
                {"event": "lead_score_above_80",  "action": "stripe_checkout_link"},
                {"event": "trial_day_7",           "action": "upsell_email"},
                {"event": "inbound_stripe_event",  "action": "log_and_compound"},
            ],
        }),
    ),
}


# ---------------------------------------------------------------------------
# Capability Shard Manager
# ---------------------------------------------------------------------------

class CapabilityShardManager:
    """
    Encrypts shard plaintext docs at startup using AWS KMS.
    At runtime, decrypts on-demand and exposes doctrine to agents.
    Shards are never stored decrypted — only live in process memory.
    """

    def __init__(self, region: str = "us-east-1") -> None:
        self._region = region
        self._kms    = None
        if BOTO_AVAILABLE:
            self._kms = boto3.client("kms", region_name=region)
        else:
            logger.warning("boto3 not available — sharding in MOCK mode")

    # ------------------------------------------------------------------
    # Seal (encrypt) a shard
    # ------------------------------------------------------------------

    def seal_shard(self, shard_id: ShardID) -> bytes:
        """Encrypt the shard's plaintext doc with its KMS key."""
        desc = SHARD_REGISTRY[shard_id]
        if self._kms is None:
            # Mock mode — base64 encode as placeholder
            blob = base64.b64encode(desc.plaintext_doc.encode())
            desc.encrypted_blob = blob
            logger.info("[MOCK] Shard %s sealed", shard_id.value)
            return blob

        try:
            resp = self._kms.encrypt(
                KeyId=desc.kms_key_alias,
                Plaintext=desc.plaintext_doc.encode(),
            )
            blob = resp["CiphertextBlob"]
            desc.encrypted_blob = blob
            logger.info("Shard %s sealed via KMS key %s",
                        shard_id.value, desc.kms_key_alias)
            return blob
        except BotoClientError as exc:
            logger.error("KMS seal failed for %s: %s", shard_id.value, exc)
            raise

    def seal_all(self) -> None:
        for shard_id in ShardID:
            self.seal_shard(shard_id)

    # ------------------------------------------------------------------
    # Unseal (decrypt) a shard — returns parsed doctrine dict
    # ------------------------------------------------------------------

    def unseal_shard(self, shard_id: ShardID) -> Dict[str, Any]:
        """Decrypt shard on-demand; return doctrine dict."""
        desc = SHARD_REGISTRY[shard_id]
        if desc.encrypted_blob is None:
            raise RuntimeError(f"Shard {shard_id.value} has not been sealed yet")

        if self._kms is None:
            # Mock mode
            plaintext = base64.b64decode(desc.encrypted_blob).decode()
            logger.info("[MOCK] Shard %s unsealed", shard_id.value)
        else:
            try:
                resp = self._kms.decrypt(CiphertextBlob=desc.encrypted_blob)
                plaintext = resp["Plaintext"].decode()
                logger.info("Shard %s unsealed via KMS", shard_id.value)
            except BotoClientError as exc:
                logger.error("KMS unseal failed for %s: %s", shard_id.value, exc)
                raise

        desc.loaded_at = time.time()
        return json.loads(plaintext)

    def get_reasoning_doctrine(self) -> Dict[str, Any]:
        return self.unseal_shard(ShardID.REASONING)

    def get_monetization_doctrine(self) -> Dict[str, Any]:
        return self.unseal_shard(ShardID.MONETIZATION)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

SHARD_MANAGER = CapabilityShardManager()
