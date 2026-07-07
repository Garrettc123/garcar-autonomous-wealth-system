from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None
    REDIS_AVAILABLE = False

log = logging.getLogger("garcar.event_bus")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class IntegrationEvent:
    event_type: str
    source: str
    payload: Dict[str, Any]
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_event(
    event_type: str,
    payload: Dict[str, Any],
    *,
    source: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    status: str = "pending",
) -> Dict[str, Any]:
    event = IntegrationEvent(
        event_type=event_type,
        source=source or os.getenv(
            "GITHUB_REPOSITORY",
            "Garrettc123/garcar-autonomous-wealth-system",
        ),
        payload=payload,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=correlation_id,
        metadata=metadata or {},
        status=status,
    )
    return event.to_dict()


class IntegrationEventBus:
    DEFAULT_MAX_BUFFER_SIZE = int(os.getenv("GARCAR_EVENT_BUFFER_SIZE", "1000"))
    DEFAULT_BUFFER_TRIM_SIZE = int(os.getenv("GARCAR_EVENT_BUFFER_TRIM_SIZE", "500"))
    DEFAULT_MAX_PENDING_TASKS = int(os.getenv("GARCAR_EVENT_MAX_PENDING_TASKS", "100"))

    def __init__(
        self,
        *,
        redis_url: Optional[str] = None,
        stream_name: Optional[str] = None,
        status_stream_name: Optional[str] = None,
        dispatched_set_name: Optional[str] = None,
        use_redis: Optional[bool] = None,
    ) -> None:
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.stream_name = stream_name or os.getenv("GARCAR_EVENT_STREAM", "garcar:events")
        self.status_stream_name = status_stream_name or os.getenv(
            "GARCAR_EVENT_STATUS_STREAM",
            "garcar:event-status",
        )
        self.dispatched_set_name = dispatched_set_name or os.getenv(
            "GARCAR_FULFILLMENT_DISPATCH_SET",
            "garcar:fulfillment:dispatched",
        )
        self.use_redis = REDIS_AVAILABLE if use_redis is None else use_redis
        self.max_buffer_size = self.DEFAULT_MAX_BUFFER_SIZE
        self.buffer_trim_size = min(self.DEFAULT_BUFFER_TRIM_SIZE, self.max_buffer_size)
        self.max_pending_tasks = self.DEFAULT_MAX_PENDING_TASKS
        self._redis: Optional[Any] = None
        self._buffer: List[Dict[str, Any]] = []
        self._dispatched: Set[str] = set()
        self._pending_tasks: Set[asyncio.Task] = set()
        self._last_error: Optional[str] = None
        self._next_retry_at = 0.0

    async def _connect(self) -> Optional[Any]:
        if not self.use_redis:
            return None
        if self._redis is not None:
            return self._redis
        if time.time() < self._next_retry_at:
            return None
        try:
            self._redis = await aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._redis = None
            self._next_retry_at = time.time() + 30
            log.warning("Redis unavailable for event bus, using memory fallback: %s", exc)
            return None

    async def publish_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self._buffer.append(event)
        if len(self._buffer) > self.max_buffer_size:
            self._buffer = self._buffer[-self.buffer_trim_size:]

        redis = await self._connect()
        if redis is not None:
            try:
                await redis.xadd(self.stream_name, {"payload": json.dumps(event)})
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                log.warning("Redis publish failed, keeping event in memory: %s", exc)
        return event

    async def read_events(
        self,
        *,
        event_type: Optional[str] = None,
        count: int = 100,
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        redis = await self._connect()
        if redis is not None:
            try:
                entries = await redis.xrevrange(self.stream_name, count=count)
                for msg_id, data in reversed(entries):
                    try:
                        event = json.loads(data.get("payload", "{}"))
                        event["_redis_id"] = msg_id
                        events.append(event)
                    except json.JSONDecodeError:
                        continue
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                log.warning("Redis read failed, falling back to memory: %s", exc)
        if not events:
            events = list(self._buffer[-count:])
        if event_type:
            events = [event for event in events if event.get("event_type") == event_type]
        return events

    async def is_dispatched(self, event_id: str) -> bool:
        redis = await self._connect()
        if redis is not None:
            try:
                return bool(await redis.sismember(self.dispatched_set_name, event_id))
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                log.warning("Redis dispatch lookup failed, falling back to memory: %s", exc)
        return event_id in self._dispatched

    async def mark_dispatched(
        self,
        event_id: str,
        *,
        dispatcher: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._dispatched.add(event_id)
        redis = await self._connect()
        status_entry = {
            "event_id": event_id,
            "dispatcher": dispatcher,
            "timestamp": utc_now(),
            "result": result or {},
        }
        if redis is not None:
            try:
                await redis.sadd(self.dispatched_set_name, event_id)
                await redis.xadd(
                    self.status_stream_name,
                    {"payload": json.dumps(status_entry)},
                )
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                log.warning("Redis dispatch mark failed, keeping local state: %s", exc)

    async def get_health(self) -> Dict[str, Any]:
        redis = await self._connect()
        return {
            "enabled": True,
            "backend": "redis" if redis is not None else "memory",
            "redis_configured": self.use_redis,
            "redis_connected": redis is not None,
            "stream": self.stream_name,
            "buffered_events": len(self._buffer),
            "last_error_present": self._last_error is not None,
        }

    def _run_sync(self, coro, *, allow_background: bool = False, method_name: str):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        if allow_background:
            if len(self._pending_tasks) >= self.max_pending_tasks:
                raise RuntimeError("Too many pending event bus tasks")
            task = loop.create_task(coro)
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
            task.add_done_callback(self._log_background_task_failure)
            return task
        raise RuntimeError(
            f"Cannot call {method_name}_sync from async context. Use await {method_name}() instead.",
        )

    @staticmethod
    def _log_background_task_failure(task: asyncio.Task) -> None:
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001
            log.warning("Background event bus task failed: %s", exc)

    def publish_sync(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self._run_sync(
            self.publish_event(event),
            allow_background=True,
            method_name="publish_event",
        )
        return event

    def read_events_sync(
        self,
        *,
        event_type: Optional[str] = None,
        count: int = 100,
    ) -> List[Dict[str, Any]]:
        return self._run_sync(
            self.read_events(event_type=event_type, count=count),
            method_name="read_events",
        )

    def is_dispatched_sync(self, event_id: str) -> bool:
        return self._run_sync(
            self.is_dispatched(event_id),
            method_name="is_dispatched",
        )

    def mark_dispatched_sync(
        self,
        event_id: str,
        *,
        dispatcher: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._run_sync(
            self.mark_dispatched(event_id, dispatcher=dispatcher, result=result),
            method_name="mark_dispatched",
        )

    def health_sync(self) -> Dict[str, Any]:
        return self._run_sync(self.get_health(), method_name="get_health")


integration_event_bus = IntegrationEventBus()
