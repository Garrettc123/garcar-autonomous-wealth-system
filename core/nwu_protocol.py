"""NWU Protocol — Network-Wide Unit Data Monetization Layer
Garcar Enterprise | Garrett Carrol

Every data packet produced by the system carries an NWU token.
NWU tokens accrue value based on: data quality score, downstream usage count,
and revenue attribution. This file implements the full protocol:
  1. Token minting (on data creation)
  2. Value accrual (on downstream consumption)
  3. Revenue settlement (on conversion events)
  4. Ledger persistence
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("nwu_protocol")
LEDGER_PATH = Path("nwu_ledger.json")


@dataclass
class NWUToken:
    token_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_node: str = ""
    data_type: str = ""             # e.g. "lead", "signal", "metric", "event"
    data_hash: str = ""
    quality_score: float = 1.0      # 0.0–1.0
    accrued_value: float = 0.0      # USD equivalent
    usage_count: int = 0
    revenue_attributed: float = 0.0
    minted_at: float = field(default_factory=time.time)
    settled_at: Optional[float] = None
    status: str = "active"          # "active"|"settled"|"expired"
    lineage: List[str] = field(default_factory=list)  # token_ids of parent data

    @property
    def nwu_value(self) -> float:
        """NWU value = quality × log(1+usage) × revenue_factor"""
        import math
        return round(
            self.quality_score * math.log1p(self.usage_count) * (1 + self.revenue_attributed / 100),
            6
        )


class NWUProtocol:
    """Full NWU token lifecycle manager."""

    QUALITY_WEIGHTS = {
        "lead":    0.95,
        "signal":  0.80,
        "metric":  0.70,
        "event":   0.60,
        "generic": 0.50
    }

    def __init__(self):
        self.ledger: Dict[str, NWUToken] = {}
        self._total_minted = 0
        self._total_settled = 0.0
        self._load_ledger()

    # ──────────────────────────────────────────
    # Minting
    # ──────────────────────────────────────────

    def mint(self, source_node: str, data_type: str, data: Dict,
             lineage: Optional[List[str]] = None) -> NWUToken:
        data_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        quality = self.QUALITY_WEIGHTS.get(data_type, 0.5)
        # Boost quality if data has high-value fields
        if any(k in data for k in ["email", "phone", "revenue", "payment"]):
            quality = min(quality + 0.15, 1.0)
        token = NWUToken(
            source_node=source_node,
            data_type=data_type,
            data_hash=data_hash,
            quality_score=quality,
            lineage=lineage or []
        )
        self.ledger[token.token_id] = token
        self._total_minted += 1
        self._persist()
        log.info(f"NWU minted: {token.token_id[:8]} [{data_type}] q={quality:.2f}")
        return token

    # ──────────────────────────────────────────
    # Accrual
    # ──────────────────────────────────────────

    def record_usage(self, token_id: str, consumer_node: str,
                     revenue_delta: float = 0.0) -> Optional[NWUToken]:
        if token_id not in self.ledger:
            return None
        token = self.ledger[token_id]
        token.usage_count += 1
        token.revenue_attributed += revenue_delta
        token.accrued_value = token.nwu_value
        self._persist()
        log.debug(f"NWU usage: {token_id[:8]} by {consumer_node}, rev+{revenue_delta:.4f}")
        return token

    # ──────────────────────────────────────────
    # Settlement
    # ──────────────────────────────────────────

    def settle(self, token_id: str) -> float:
        if token_id not in self.ledger:
            return 0.0
        token = self.ledger[token_id]
        if token.status == "settled":
            return token.accrued_value
        token.status = "settled"
        token.settled_at = time.time()
        self._total_settled += token.accrued_value
        self._persist()
        log.info(f"NWU settled: {token_id[:8]} → ${token.accrued_value:.4f}")
        return token.accrued_value

    def settle_all(self) -> float:
        total = sum(self.settle(tid) for tid, t in list(self.ledger.items())
                    if t.status == "active" and t.usage_count > 0)
        log.info(f"NWU batch settlement: ${total:.4f}")
        return total

    # ──────────────────────────────────────────
    # Reporting
    # ──────────────────────────────────────────

    def portfolio(self) -> Dict:
        active = [t for t in self.ledger.values() if t.status == "active"]
        return {
            "total_minted": self._total_minted,
            "active_tokens": len(active),
            "total_settled_usd": round(self._total_settled, 4),
            "unrealized_value": round(sum(t.nwu_value for t in active), 4),
            "top_tokens": sorted(
                [asdict(t) for t in active],
                key=lambda x: x["accrued_value"], reverse=True
            )[:10]
        }

    # ──────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────

    def _persist(self):
        data = {
            "total_minted": self._total_minted,
            "total_settled": self._total_settled,
            "tokens": {k: asdict(v) for k, v in list(self.ledger.items())[-1000:]}
        }
        with open(LEDGER_PATH, "w") as f:
            json.dump(data, f, indent=2)

    def _load_ledger(self):
        if not LEDGER_PATH.exists():
            return
        try:
            with open(LEDGER_PATH) as f:
                data = json.load(f)
            self._total_minted = data.get("total_minted", 0)
            self._total_settled = data.get("total_settled", 0.0)
            for k, v in data.get("tokens", {}).items():
                self.ledger[k] = NWUToken(**v)
        except Exception as e:
            log.error(f"Ledger load failed: {e}")


nwu = NWUProtocol()
