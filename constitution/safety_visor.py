"""
Phase 4 — Safety Visor
Parallel monitoring process using Redis for real-time
pattern detection and escalation flagging.

Run as a standalone asyncio process alongside the FastAPI server:
    python -m constitution.safety_visor
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger("garcar.visor")

REDIS_URL          = os.getenv("REDIS_URL", "redis://localhost:6379")
ACTION_STREAM      = "garcar:actions"         # Redis Stream key
VIOLATION_STREAM   = "garcar:violations"      # Escalation sink
PATTERN_WINDOW_SEC = 300                       # 5-minute sliding window


# ---------------------------------------------------------------------------
# Anomaly Patterns
# ---------------------------------------------------------------------------

@dataclass
class AnomalyPattern:
    pattern_id:   str
    description:  str
    # A pure function (recent_actions: list[dict]) -> bool
    detector:     Callable[[List[Dict[str, Any]]], bool]


PATTERNS: List[AnomalyPattern] = [
    AnomalyPattern(
        pattern_id  = "AP-001",
        description = "Burst rate: >20 Stripe charges in 5-minute window",
        detector    = lambda actions: (
            sum(1 for a in actions if a.get("action_type") == "stripe_charge") > 20
        ),
    ),
    AnomalyPattern(
        pattern_id  = "AP-002",
        description = "Repeated constitution blocks from same agent (>3 blocks)",
        detector    = lambda actions: (
            sum(1 for a in actions
                if a.get("verdict") == "BLOCKED") > 3
        ),
    ),
    AnomalyPattern(
        pattern_id  = "AP-003",
        description = "GitHub dispatch storm: >10 dispatches in 5-minute window",
        detector    = lambda actions: (
            sum(1 for a in actions
                if a.get("action_type") == "github_dispatch") > 10
        ),
    ),
    AnomalyPattern(
        pattern_id  = "AP-004",
        description = "Suspicious total outbound spend: >$1,000 in 5-minute window",
        detector    = lambda actions: (
            sum(
                float(a.get("params", {}).get("amount_usd", 0))
                for a in actions
                if a.get("action_type") == "stripe_charge"
            ) > 1000.0
        ),
    ),
]


# ---------------------------------------------------------------------------
# Safety Visor
# ---------------------------------------------------------------------------

class SafetyVisor:
    """
    Reads the Redis action stream, maintains a rolling window of
    recent actions, and runs anomaly pattern detectors every cycle.
    On anomaly detection, writes an escalation record to VIOLATION_STREAM.
    """

    def __init__(self) -> None:
        self._redis:   Optional[Any] = None
        self._window:  List[Dict[str, Any]] = []
        self._last_id  = "0"

    async def _connect(self) -> None:
        if REDIS_AVAILABLE:
            self._redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
            logger.info("SafetyVisor connected to Redis at %s", REDIS_URL)
        else:
            logger.warning("Redis not available — SafetyVisor running in LOG-ONLY mode")

    async def _read_new_actions(self) -> List[Dict[str, Any]]:
        if self._redis is None:
            return []
        entries = await self._redis.xread(
            {ACTION_STREAM: self._last_id}, count=100, block=1000
        )
        actions = []
        for _stream, messages in entries:
            for msg_id, data in messages:
                self._last_id = msg_id
                try:
                    action = json.loads(data.get("payload", "{}"))
                    action["_redis_id"] = msg_id
                    actions.append(action)
                except json.JSONDecodeError:
                    pass
        return actions

    def _prune_window(self) -> None:
        cutoff = time.time() - PATTERN_WINDOW_SEC
        self._window = [
            a for a in self._window
            if float(a.get("timestamp", 0)) > cutoff
        ]

    async def _escalate(self, pattern: AnomalyPattern) -> None:
        escalation = {
            "pattern_id":  pattern.pattern_id,
            "description": pattern.description,
            "window_size": len(self._window),
            "timestamp":   time.time(),
        }
        logger.warning("ESCALATION %s — %s", pattern.pattern_id, pattern.description)
        if self._redis is not None:
            await self._redis.xadd(
                VIOLATION_STREAM,
                {"payload": json.dumps(escalation)},
            )

    async def run_cycle(self) -> None:
        new_actions = await self._read_new_actions()
        self._window.extend(new_actions)
        self._prune_window()

        for pattern in PATTERNS:
            try:
                if pattern.detector(self._window):
                    await self._escalate(pattern)
            except Exception as exc:  # noqa: BLE001
                logger.error("Pattern %s eval error: %s", pattern.pattern_id, exc)

    async def run_forever(self, interval: float = 5.0) -> None:
        await self._connect()
        logger.info("SafetyVisor active — polling every %.1fs", interval)
        while True:
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001
                logger.error("Visor cycle error: %s", exc)
            await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    visor = SafetyVisor()
    asyncio.run(visor.run_forever())
