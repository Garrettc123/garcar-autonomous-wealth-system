"""Apex Orchestrator — Garcar Enterprise
The single command-and-control brain. Boots all subsystems, wires them
together, and runs the infinite autonomous loop.

Boot sequence:
  1. RHNS Engine
  2. Self-Discovery Engine
  3. NWU Protocol
  4. Autonomous Revenue Loop
  5. Domain controllers (healthcare, legal, contractor, roofing, surveying)
  6. GitHub Actions dispatcher
  7. Telemetry + health watchdog
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import signal
import time
from typing import Dict, List

from core.rhns_engine import RHNSEngine, NetworkNode, NodeTier
from core.self_discovery_engine import SelfDiscoveryEngine
from core.nwu_protocol import NWUProtocol
from core.autonomous_revenue_loop import AutonomousRevenueLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [APEX] %(levelname)s %(message)s"
)
log = logging.getLogger("apex")


DOMAINS = [
    {"name": "healthcare",  "capabilities": ["ehr_intake", "scheduling", "billing", "compliance"]},
    {"name": "legal",       "capabilities": ["contract_review", "intake", "billing", "court_calendar"]},
    {"name": "contractor",  "capabilities": ["lead_gen", "estimating", "scheduling", "invoicing"]},
    {"name": "roofing",     "capabilities": ["storm_leads", "estimating", "permitting", "invoicing"]},
    {"name": "surveying",   "capabilities": ["site_analysis", "report_gen", "gis", "billing"]},
]


class ApexOrchestrator:
    """Master orchestrator — boots and governs the entire Garcar system."""

    def __init__(self):
        self.rhns = RHNSEngine()
        self.discovery = SelfDiscoveryEngine(rhns=self.rhns)
        self.nwu = NWUProtocol()
        self.revenue = AutonomousRevenueLoop(nwu=self.nwu, rhns=self.rhns)
        self._running = False
        self._boot_time: float = 0.0

    # ──────────────────────────────────────────
    # Boot
    # ──────────────────────────────────────────

    async def boot(self):
        self._boot_time = time.time()
        log.info("═" * 60)
        log.info("  GARCAR APEX ORCHESTRATOR BOOTING")
        log.info("═" * 60)

        # 1. Register apex node
        apex = NetworkNode(
            name="apex-orchestrator",
            tier=NodeTier.APEX,
            domain="system",
            capabilities=["orchestrate", "route", "govern", "evolve"]
        )
        await self.rhns.register(apex)

        # 2. Register domain controllers
        for domain in DOMAINS:
            controller = NetworkNode(
                name=f"{domain['name']}-controller",
                tier=NodeTier.DOMAIN,
                domain=domain["name"],
                capabilities=domain["capabilities"],
                parent_id=apex.node_id
            )
            await self.rhns.register(controller)
            # Register leaf agents under each domain
            for cap in domain["capabilities"]:
                agent = NetworkNode(
                    name=f"{domain['name']}-{cap}-agent",
                    tier=NodeTier.AGENT,
                    domain=domain["name"],
                    capabilities=[cap],
                    parent_id=controller.node_id
                )
                await self.rhns.register(agent)

        log.info(f"RHNS: {len(self.rhns.nodes)} nodes registered")

        # 3. Self-discovery scan
        scan = await self.discovery.scan(".")
        log.info(f"Discovery: {scan['total_capabilities']} capabilities cataloged, "
                 f"{scan['breakthroughs']} breakthroughs")

        # 4. Wire RHNS hooks
        self.rhns.on("node.evolution", self._on_evolution)
        self.rhns.on("revenue.cycle",  self._on_revenue_cycle)
        self.rhns.on("system.discovery", self._on_discovery)

        log.info("Apex boot complete")
        log.info("═" * 60)

    # ──────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────

    async def run(self):
        await self.boot()
        self._running = True

        tasks = [
            asyncio.create_task(self.rhns.run(),         name="rhns"),
            asyncio.create_task(self.discovery.run("."), name="discovery"),
            asyncio.create_task(self._revenue_loop(),    name="revenue"),
            asyncio.create_task(self._watchdog(),        name="watchdog"),
            asyncio.create_task(self._telemetry_emit(),  name="telemetry"),
        ]

        log.info(f"All {len(tasks)} subsystems running")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Shutdown signal received")
        finally:
            self._shutdown()

    async def _revenue_loop(self):
        """Infinite revenue loop with synthetic lead injection (replace with real source)."""
        while self._running:
            leads = self._synthetic_leads(count=20)
            await self.revenue.run_cycle(leads)
            await asyncio.sleep(60)

    async def _watchdog(self):
        """Health monitor — logs system state every 5 minutes."""
        while self._running:
            snapshot = await self.rhns.discover()
            rev = self.revenue.summary
            nwu = self.nwu.portfolio()
            log.info(
                f"HEALTH │ nodes={snapshot['total_nodes']} active={snapshot['active_nodes']} "
                f"health={snapshot['network_health']} │ "
                f"revenue=${rev['total_revenue']:.2f} │ "
                f"NWU tokens={nwu['active_tokens']} unrealized=${nwu['unrealized_value']:.4f}"
            )
            await asyncio.sleep(300)

    async def _telemetry_emit(self):
        """Emit telemetry heartbeats for all active nodes."""
        while self._running:
            for node in list(self.rhns.nodes.values()):
                await self.rhns.heartbeat(node.node_id, {
                    "revenue_delta": 0.01,
                    "tasks_completed": 1,
                    "tasks_failed": 0
                })
            await asyncio.sleep(30)

    # ──────────────────────────────────────────
    # Event handlers
    # ──────────────────────────────────────────

    async def _on_evolution(self, data: Dict):
        log.warning(f"EVOLUTION EVENT: {data['name']} weight={data['weight']:.3f}")

    async def _on_revenue_cycle(self, data: Dict):
        log.info(f"REVENUE CYCLE #{data['cycle']}: gross=${data['gross_revenue']:.2f} "
                 f"retained=${data['net_retained']:.2f}")

    async def _on_discovery(self, data: Dict):
        log.info(f"🔬 BREAKTHROUGH: {data['capability']} score={data['breakthrough_score']}")

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    def _synthetic_leads(self, count: int = 20) -> List[Dict]:
        """Placeholder lead source — replace with real acquisition pipeline."""
        import random
        domains = ["contractor", "roofing", "healthcare", "legal", "surveying"]
        return [
            {
                "email": f"lead{i}@example.com",
                "phone": f"817-555-{1000+i}",
                "company": f"Company {i}",
                "budget": random.uniform(200, 5000),
                "domain": random.choice(domains),
                "source": "synthetic"
            }
            for i in range(count)
        ]

    def _shutdown(self):
        self._running = False
        self.rhns.stop()
        self.discovery.stop()
        self.revenue.stop()
        log.info("Apex orchestrator shutdown complete")


# ──────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────

if __name__ == "__main__":
    apex = ApexOrchestrator()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(*args):
        log.info("Signal received — initiating graceful shutdown")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        loop.run_until_complete(apex.run())
    finally:
        loop.close()
        log.info("Event loop closed")
