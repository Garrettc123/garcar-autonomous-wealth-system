"""Domain Agent Base — Garcar Enterprise
All vertical-specific agents (healthcare, legal, contractor, roofing,
surveying) inherit from this base. It handles:
  - Registration with RHNS
  - NWU token minting for every data event
  - Stripe payment initiation
  - Task execution with automatic retry and circuit breaker
  - Telemetry reporting
"""
from __future__ import annotations
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("domain_agent")


@dataclass
class TaskResult:
    task_id: str
    success: bool
    output: Any
    duration_ms: float
    revenue_impact: float = 0.0
    error: Optional[str] = None
    retries: int = 0


class CircuitBreaker:
    """Simple circuit breaker — open after 5 consecutive failures."""
    THRESHOLD = 5
    RECOVERY = 30  # seconds

    def __init__(self):
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def open(self) -> bool:
        if self._opened_at and time.time() - self._opened_at > self.RECOVERY:
            self._failures = 0
            self._opened_at = None
        return self._opened_at is not None

    def record_success(self):
        self._failures = 0
        self._opened_at = None

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.THRESHOLD:
            self._opened_at = time.time()
            log.warning("Circuit breaker OPEN")


class DomainAgentBase(ABC):
    """Abstract base for all Garcar domain agents."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2.0  # seconds, exponential backoff

    def __init__(self, name: str, domain: str, rhns=None, nwu=None):
        self.name = name
        self.domain = domain
        self.rhns = rhns
        self.nwu = nwu
        self.cb = CircuitBreaker()
        self._tasks_done = 0
        self._revenue = 0.0
        self._node_id: Optional[str] = None

    async def register(self):
        if not self.rhns:
            return
        from core.rhns_engine import NetworkNode, NodeTier
        node = NetworkNode(
            name=self.name,
            tier=NodeTier.AGENT,
            domain=self.domain,
            capabilities=self.capabilities
        )
        self._node_id = await self.rhns.register(node)
        log.info(f"{self.name} registered with RHNS")

    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        ...

    @abstractmethod
    async def execute_task(self, task: Dict) -> TaskResult:
        ...

    async def run_task(self, task: Dict) -> TaskResult:
        """Run a task with retry logic and circuit breaker protection."""
        if self.cb.open:
            return TaskResult(
                task_id=task.get("task_id", "unknown"),
                success=False,
                output=None,
                duration_ms=0,
                error="circuit_breaker_open"
            )
        retries = 0
        while retries <= self.MAX_RETRIES:
            t0 = time.perf_counter()
            try:
                result = await self.execute_task(task)
                result.duration_ms = (time.perf_counter() - t0) * 1000
                result.retries = retries
                if result.success:
                    self.cb.record_success()
                    self._tasks_done += 1
                    self._revenue += result.revenue_impact
                    if self.nwu:
                        self.nwu.mint(self.name, "event", {
                            "task_id": task.get("task_id"),
                            "revenue": result.revenue_impact
                        })
                    if self._node_id and self.rhns:
                        await self.rhns.heartbeat(self._node_id, {
                            "tasks_completed": 1,
                            "revenue_delta": result.revenue_impact
                        })
                    return result
                else:
                    self.cb.record_failure()
                    retries += 1
                    await asyncio.sleep(self.RETRY_DELAY ** retries)
            except Exception as e:
                self.cb.record_failure()
                retries += 1
                log.error(f"{self.name} task error (retry {retries}): {e}")
                if retries > self.MAX_RETRIES:
                    return TaskResult(
                        task_id=task.get("task_id", "unknown"),
                        success=False,
                        output=None,
                        duration_ms=(time.perf_counter() - t0) * 1000,
                        error=str(e),
                        retries=retries
                    )
                await asyncio.sleep(self.RETRY_DELAY ** retries)
        return TaskResult(task_id="unknown", success=False, output=None,
                         duration_ms=0, error="max_retries_exceeded")

    @property
    def stats(self) -> Dict:
        return {
            "name": self.name,
            "domain": self.domain,
            "tasks_done": self._tasks_done,
            "revenue": round(self._revenue, 4),
            "circuit_open": self.cb.open
        }
