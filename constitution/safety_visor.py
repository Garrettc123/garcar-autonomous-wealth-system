"""
Phase 4 — Safety Visor
Parallel monitoring process using Redis for real-time pattern detection.
Runs as an asyncio background task alongside the main orchestrator.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

try:
    import redis.asyncio as aioredis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False


class EscalationLevel(str, Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"
    SHUTDOWN = "SHUTDOWN"


@dataclass
class VisorEvent:
    event_id:    str
    pattern:     str
    level:       EscalationLevel
    detail:      str
    agent_id:    str
    timestamp:   float = field(default_factory=time.time)
    suppressed:  bool  = False

    def to_dict(self) -> dict:
        return self.__dict__


# ── Detection Patterns ────────────────────────────────────────────────────────

DETECTION_PATTERNS: list[dict] = [
    {
        "name":        "rapid_charge_burst",
        "description": "More than 5 Stripe charges in 60 seconds",
        "level":       EscalationLevel.CRITICAL,
        "redis_key":   "visor:stripe_charges",
        "window_sec":  60,
        "threshold":   5,
    },
    {
        "name":        "repeated_constitution_deny",
        "description": "Agent receiving 3+ DENY verdicts in 5 minutes",
        "level":       EscalationLevel.CRITICAL,
        "redis_key":   "visor:constitution_denies",
        "window_sec":  300,
        "threshold":   3,
    },
    {
        "name":        "high_value_action_spike",
        "description": "More than 2 ESCALATE-class actions in 10 minutes",
        "level":       EscalationLevel.WARNING,
        "redis_key":   "visor:escalation_events",
        "window_sec":  600,
        "threshold":   2,
    },
    {
        "name":        "external_egress_flood",
        "description": "More than 20 outbound webhook calls in 60 seconds",
        "level":       EscalationLevel.WARNING,
        "redis_key":   "visor:webhook_calls",
        "window_sec":  60,
        "threshold":   20,
    },
    {
        "name":        "kms_key_access_burst",
        "description": "KMS accessed more than 3 times in 30 seconds",
        "level":       EscalationLevel.CRITICAL,
        "redis_key":   "visor:kms_accesses",
        "window_sec":  30,
        "threshold":   3,
    },
]


# ── Safety Visor ──────────────────────────────────────────────────────────────

class SafetyVisor:
    """
    Runs as a parallel asyncio task.
    Subscribes to a Redis stream (visor:events) and evaluates detection patterns
    using Redis sliding-window counters.

    On CRITICAL: calls escalation handlers and optionally triggers a circuit breaker.
    On SHUTDOWN: broadcasts a shutdown signal to all agent consumers.
    """

    STREAM_KEY = "visor:events"
    SHUTDOWN_CHANNEL = "visor:shutdown"

    def __init__(
        self,
        redis_url:           str | None = None,
        escalation_handlers: list[Callable[[VisorEvent], None]] | None = None,
        dry_run:             bool = False,
    ) -> None:
        self._url       = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._handlers  = escalation_handlers or []
        self._dry_run   = dry_run
        self._running   = False
        self._events:   list[VisorEvent] = []
        self._redis: Any = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the visor monitoring loop."""
        self._running = True
        if _HAS_REDIS and not self._dry_run:
            self._redis = aioredis.from_url(self._url, decode_responses=True)
        await asyncio.gather(
            self._consume_stream(),
            self._sweep_patterns(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()

    # ── Event ingestion ───────────────────────────────────────────────────────

    async def record_event(self, event_type: str, agent_id: str, metadata: dict | None = None) -> None:
        """
        Record an event from any agent.
        Maps event_type to the correct Redis counter key.
        """
        key_map = {
            "stripe_charge":       "visor:stripe_charges",
            "constitution_deny":   "visor:constitution_denies",
            "escalation_event":    "visor:escalation_events",
            "webhook_call":        "visor:webhook_calls",
            "kms_access":          "visor:kms_accesses",
        }
        redis_key = key_map.get(event_type)
        if redis_key and self._redis:
            ts = time.time()
            await self._redis.zadd(redis_key, {f"{agent_id}:{ts}": ts})

        # Also push to stream for consumer
        payload = json.dumps({"type": event_type, "agent_id": agent_id, "meta": metadata or {}, "ts": time.time()})
        if self._redis:
            await self._redis.xadd(self.STREAM_KEY, {"data": payload}, maxlen=10000)

    # ── Pattern sweep ─────────────────────────────────────────────────────────

    async def _sweep_patterns(self) -> None:
        """Periodically evaluate all detection patterns."""
        while self._running:
            for pattern in DETECTION_PATTERNS:
                await self._evaluate_pattern(pattern)
            await asyncio.sleep(5)

    async def _evaluate_pattern(self, pattern: dict) -> None:
        if not self._redis:
            return
        now    = time.time()
        window = now - pattern["window_sec"]
        count  = await self._redis.zcount(pattern["redis_key"], window, now)
        if count >= pattern["threshold"]:
            import uuid
            evt = VisorEvent(
                event_id=str(uuid.uuid4()),
                pattern=pattern["name"],
                level=pattern["level"],
                detail=f"{pattern['description']} — count={count} in {pattern['window_sec']}s",
                agent_id="visor:sweep",
            )
            await self._escalate(evt)

    # ── Stream consumer ───────────────────────────────────────────────────────

    async def _consume_stream(self) -> None:
        if not self._redis:
            # Dry run: sleep loop
            while self._running:
                await asyncio.sleep(1)
            return
        last_id = "0"
        while self._running:
            try:
                msgs = await self._redis.xread({self.STREAM_KEY: last_id}, block=1000, count=50)
                for _, entries in (msgs or []):
                    for msg_id, data in entries:
                        last_id = msg_id
                        # Pass to pattern evaluation on next sweep
            except Exception:
                await asyncio.sleep(2)

    # ── Escalation ────────────────────────────────────────────────────────────

    async def _escalate(self, event: VisorEvent) -> None:
        self._events.append(event)
        for handler in self._handlers:
            try:
                handler(event)
            except Exception:
                pass

        if event.level == EscalationLevel.SHUTDOWN:
            if self._redis:
                await self._redis.publish(self.SHUTDOWN_CHANNEL, json.dumps(event.to_dict()))

        # Log to Redis
        if self._redis:
            await self._redis.lpush("visor:escalations", json.dumps(event.to_dict()))
            await self._redis.ltrim("visor:escalations", 0, 999)

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        return [e.to_dict() for e in self._events[-limit:]]


# ── FastAPI integration helper ────────────────────────────────────────────────

async def start_visor_background(app: Any, redis_url: str | None = None) -> SafetyVisor:
    """Call from app lifespan or startup event to run visor as a background task."""
    visor = SafetyVisor(redis_url=redis_url)
    asyncio.create_task(visor.start())
    app.state.safety_visor = visor
    return visor
