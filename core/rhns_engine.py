"""RHNS — Recursive Hierarchical Network System Engine
Garcar Enterprise | Garrett Carrol
The self-organizing intelligence substrate. Every agent, node, and service
registers here. The RHNS routes, scores, and re-weights the entire network
based on real-time performance telemetry.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO, format="%(asctime)s [RHNS] %(levelname)s %(message)s")
log = logging.getLogger("rhns")


class NodeTier(str, Enum):
    APEX = "apex"       # Master orchestrator — 1 per cluster
    DOMAIN = "domain"   # Domain controller — 1 per vertical
    AGENT = "agent"     # Leaf worker — many per domain
    SENSOR = "sensor"   # Passive telemetry collector


class NodeState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    EVOLVING = "evolving"  # Self-modification in progress


@dataclass
class NetworkNode:
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    tier: NodeTier = NodeTier.AGENT
    state: NodeState = NodeState.IDLE
    domain: str = "general"
    capabilities: List[str] = field(default_factory=list)
    weight: float = 1.0          # Performance weight — auto-adjusted
    trust_score: float = 1.0     # 0.0–1.0
    revenue_generated: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 1.0

    @property
    def fingerprint(self) -> str:
        data = f"{self.node_id}{self.name}{self.domain}{self.tier}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict:
        return asdict(self)


class RHNSEngine:
    """Recursive Hierarchical Network System — production core.

    Architecture:
        APEX (1)
         └─ DOMAIN controllers (N per vertical)
              └─ AGENT workers (M per domain)
                   └─ SENSOR collectors (passive)

    The engine continuously:
        1. Collects telemetry from all nodes
        2. Re-weights nodes by performance (revenue, success rate, latency)
        3. Routes new tasks to the highest-weight capable node
        4. Triggers self-evolution when a node's weight drops below threshold
        5. Broadcasts network-wide discovery events
    """

    EVOLUTION_THRESHOLD = 0.35   # weight below this → trigger evolution
    PRUNE_TIMEOUT = 300          # seconds without heartbeat → mark offline
    REWEIGHT_INTERVAL = 60       # seconds between re-weight cycles

    def __init__(self):
        self.nodes: Dict[str, NetworkNode] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.event_bus: List[Dict] = []          # in-memory; swap for Redis pubsub
        self._running = False
        self._hooks: Dict[str, List[Callable]] = {}
        self._apex_id: Optional[str] = None
        self._lock = asyncio.Lock()
        log.info("RHNS Engine initialized")

    # ──────────────────────────────────────────
    # Node registration & lifecycle
    # ──────────────────────────────────────────

    async def register(self, node: NetworkNode) -> str:
        async with self._lock:
            self.nodes[node.node_id] = node
            if node.tier == NodeTier.APEX:
                self._apex_id = node.node_id
            if node.parent_id and node.parent_id in self.nodes:
                self.nodes[node.parent_id].children.append(node.node_id)
            log.info(f"Registered [{node.tier.value}] {node.name} ({node.node_id[:8]})")
            await self._emit("node.registered", node.to_dict())
            return node.node_id

    async def heartbeat(self, node_id: str, metrics: Optional[Dict] = None):
        if node_id not in self.nodes:
            return
        node = self.nodes[node_id]
        node.last_heartbeat = time.time()
        node.state = NodeState.ACTIVE
        if metrics:
            node.revenue_generated += metrics.get("revenue_delta", 0.0)
            node.tasks_completed += metrics.get("tasks_completed", 0)
            node.tasks_failed += metrics.get("tasks_failed", 0)
        await self._reweight_node(node)

    async def _reweight_node(self, node: NetworkNode):
        """Compute new weight from revenue, success rate, and recency."""
        recency = 1.0 - min((time.time() - node.last_heartbeat) / self.PRUNE_TIMEOUT, 1.0)
        node.weight = (
            0.40 * node.success_rate +
            0.35 * min(node.revenue_generated / 1000, 1.0) +
            0.25 * recency
        )
        if node.weight < self.EVOLUTION_THRESHOLD and node.state != NodeState.EVOLVING:
            await self._trigger_evolution(node)

    async def _trigger_evolution(self, node: NetworkNode):
        node.state = NodeState.EVOLVING
        log.warning(f"Evolution triggered for {node.name} (weight={node.weight:.3f})")
        await self._emit("node.evolution", {
            "node_id": node.node_id,
            "name": node.name,
            "weight": node.weight,
            "reason": "below_threshold"
        })
        # In production: spawn a new version of the node, run A/B comparison,
        # promote winner, retire loser. Here we reset and mark active.
        await asyncio.sleep(0.1)
        node.tasks_failed = 0
        node.tasks_completed = max(node.tasks_completed, 1)
        node.weight = 0.5
        node.state = NodeState.ACTIVE
        log.info(f"Evolution complete for {node.name}")

    # ──────────────────────────────────────────
    # Task routing
    # ──────────────────────────────────────────

    async def route_task(self, capability: str, payload: Dict) -> Optional[str]:
        """Route a task to the best available node with the given capability."""
        candidates = [
            n for n in self.nodes.values()
            if capability in n.capabilities
            and n.state in (NodeState.ACTIVE, NodeState.IDLE)
        ]
        if not candidates:
            log.warning(f"No node available for capability: {capability}")
            return None
        best = max(candidates, key=lambda n: n.weight * n.trust_score)
        best.state = NodeState.ACTIVE
        task_id = str(uuid.uuid4())
        await self.task_queue.put({"task_id": task_id, "node_id": best.node_id,
                                    "capability": capability, "payload": payload})
        await self._emit("task.routed", {"task_id": task_id, "node": best.name,
                                          "capability": capability})
        log.info(f"Task {task_id[:8]} → {best.name} [{capability}]")
        return task_id

    # ──────────────────────────────────────────
    # Network-wide discovery
    # ──────────────────────────────────────────

    async def discover(self) -> Dict:
        """Snapshot of the entire network topology and state."""
        total_revenue = sum(n.revenue_generated for n in self.nodes.values())
        active = [n for n in self.nodes.values() if n.state == NodeState.ACTIVE]
        degraded = [n for n in self.nodes.values() if n.state == NodeState.DEGRADED]
        snapshot = {
            "timestamp": time.time(),
            "total_nodes": len(self.nodes),
            "active_nodes": len(active),
            "degraded_nodes": len(degraded),
            "total_revenue": round(total_revenue, 4),
            "apex_id": self._apex_id,
            "network_health": round(
                sum(n.weight for n in self.nodes.values()) / max(len(self.nodes), 1), 4
            ),
            "nodes": [n.to_dict() for n in self.nodes.values()]
        }
        await self._emit("network.discovered", snapshot)
        return snapshot

    # ──────────────────────────────────────────
    # Event bus
    # ──────────────────────────────────────────

    async def _emit(self, event: str, data: Dict):
        entry = {"event": event, "ts": time.time(), "data": data}
        self.event_bus.append(entry)
        for hook in self._hooks.get(event, []):
            try:
                await asyncio.ensure_future(hook(data)) if asyncio.iscoroutinefunction(hook) \
                    else hook(data)
            except Exception as e:
                log.error(f"Hook error on {event}: {e}")

    def on(self, event: str, hook: Callable):
        self._hooks.setdefault(event, []).append(hook)

    # ──────────────────────────────────────────
    # Background run loop
    # ──────────────────────────────────────────

    async def run(self):
        self._running = True
        log.info("RHNS run loop started")
        while self._running:
            await self._prune_offline()
            await self._global_reweight()
            await asyncio.sleep(self.REWEIGHT_INTERVAL)

    async def _prune_offline(self):
        now = time.time()
        for node in self.nodes.values():
            if now - node.last_heartbeat > self.PRUNE_TIMEOUT:
                if node.state != NodeState.OFFLINE:
                    node.state = NodeState.OFFLINE
                    log.warning(f"Node offline: {node.name}")
                    await self._emit("node.offline", {"node_id": node.node_id})

    async def _global_reweight(self):
        for node in self.nodes.values():
            if node.state != NodeState.OFFLINE:
                await self._reweight_node(node)

    def stop(self):
        self._running = False


# ──────────────────────────────────────────
# Singleton instance
# ──────────────────────────────────────────
rhns = RHNSEngine()
