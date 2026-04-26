"""Self-Discovery Engine — Garcar Enterprise
The system observes itself, catalogs its own capabilities, gaps, and
evolution trajectory. This is the scientific rigor layer: every component
is measured, compared against a breakthrough threshold, and logged as a
discovery event.
"""
from __future__ import annotations
import asyncio
import importlib
import inspect
import json
import logging
import os
import pkgutil
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("self_discovery")


@dataclass
class CapabilityRecord:
    name: str
    module: str
    kind: str          # "function"|"class"|"service"|"workflow"
    status: str = "unknown"   # "verified"|"degraded"|"missing"
    latency_ms: float = 0.0
    last_tested: float = field(default_factory=time.time)
    error: Optional[str] = None
    breakthrough_score: float = 0.0  # 0–1 novelty × impact
    metadata: Dict[str, Any] = field(default_factory=dict)


class SelfDiscoveryEngine:
    """Autonomously scans, probes, and catalogs the live system.

    Breakthrough score = 0.4 × novelty + 0.3 × coverage_delta + 0.3 × revenue_impact
    A score > 0.75 triggers a DISCOVERY event logged to the event bus and
    written to discovery_log.json.
    """

    BREAKTHROUGH_THRESHOLD = 0.75
    SCAN_INTERVAL = 120  # seconds
    DISCOVERY_LOG = Path("discovery_log.json")

    def __init__(self, rhns=None):
        self.rhns = rhns
        self.registry: Dict[str, CapabilityRecord] = {}
        self.discoveries: List[Dict] = []
        self._known_caps: set = set()
        self._running = False
        if self.DISCOVERY_LOG.exists():
            with open(self.DISCOVERY_LOG) as f:
                self.discoveries = json.load(f)
        log.info("SelfDiscoveryEngine initialized")

    # ──────────────────────────────────────────
    # Scan
    # ──────────────────────────────────────────

    async def scan(self, root_path: str = ".") -> Dict:
        """Walk the project, probe every Python module, record capabilities."""
        root = Path(root_path).resolve()
        found: List[CapabilityRecord] = []

        for py_file in root.rglob("*.py"):
            if any(skip in str(py_file) for skip in [".venv", "__pycache__", "test_"]):
                continue
            module_name = self._path_to_module(py_file, root)
            caps = await self._probe_module(module_name, py_file)
            found.extend(caps)

        new_caps = {r.name for r in found} - self._known_caps
        coverage_delta = len(new_caps) / max(len(found), 1)

        for record in found:
            is_new = record.name not in self._known_caps
            record.breakthrough_score = self._score(
                novelty=1.0 if is_new else 0.1,
                coverage_delta=coverage_delta,
                revenue_impact=self._estimate_revenue_impact(record)
            )
            self.registry[record.name] = record
            if record.breakthrough_score >= self.BREAKTHROUGH_THRESHOLD:
                await self._log_discovery(record)

        self._known_caps = {r.name for r in found}
        snapshot = {
            "timestamp": time.time(),
            "total_capabilities": len(found),
            "new_capabilities": len(new_caps),
            "breakthroughs": len(self.discoveries),
            "coverage_delta": round(coverage_delta, 4)
        }
        log.info(f"Scan complete: {len(found)} caps, {len(new_caps)} new, {len(self.discoveries)} breakthroughs")
        return snapshot

    async def _probe_module(self, module_name: str, path: Path) -> List[CapabilityRecord]:
        records = []
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None:
                return records
            mod = importlib.util.module_from_spec(spec)
            t0 = time.perf_counter()
            spec.loader.exec_module(mod)
            latency = (time.perf_counter() - t0) * 1000

            for name, obj in inspect.getmembers(mod):
                if name.startswith("_"):
                    continue
                if inspect.isfunction(obj):
                    records.append(CapabilityRecord(
                        name=f"{module_name}.{name}",
                        module=module_name,
                        kind="function",
                        status="verified",
                        latency_ms=round(latency, 2)
                    ))
                elif inspect.isclass(obj):
                    records.append(CapabilityRecord(
                        name=f"{module_name}.{name}",
                        module=module_name,
                        kind="class",
                        status="verified",
                        latency_ms=round(latency, 2)
                    ))
        except Exception as e:
            records.append(CapabilityRecord(
                name=f"{module_name}.__import__",
                module=module_name,
                kind="module",
                status="degraded",
                error=str(e)
            ))
        return records

    # ──────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────

    def _score(self, novelty: float, coverage_delta: float, revenue_impact: float) -> float:
        return round(0.40 * novelty + 0.30 * coverage_delta + 0.30 * revenue_impact, 4)

    def _estimate_revenue_impact(self, record: CapabilityRecord) -> float:
        HIGH_IMPACT = ["stripe", "revenue", "payment", "acquisition", "webhook",
                       "affiliate", "lead", "billing", "wallet", "compounding"]
        for kw in HIGH_IMPACT:
            if kw in record.name.lower():
                return 0.9
        MED_IMPACT = ["orchestrat", "agent", "deploy", "monitor", "rhns", "nwu"]
        for kw in MED_IMPACT:
            if kw in record.name.lower():
                return 0.6
        return 0.2

    # ──────────────────────────────────────────
    # Discovery logging
    # ──────────────────────────────────────────

    async def _log_discovery(self, record: CapabilityRecord):
        entry = {
            "discovery_id": f"D-{int(time.time())}-{record.name[:20]}",
            "ts": time.time(),
            "capability": record.name,
            "breakthrough_score": record.breakthrough_score,
            "kind": record.kind,
            "module": record.module
        }
        self.discoveries.append(entry)
        self._persist_discoveries()
        log.info(f"🔬 DISCOVERY: {record.name} (score={record.breakthrough_score})")
        if self.rhns:
            await self.rhns._emit("system.discovery", entry)

    def _persist_discoveries(self):
        with open(self.DISCOVERY_LOG, "w") as f:
            json.dump(self.discoveries[-500:], f, indent=2)  # keep last 500

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    @staticmethod
    def _path_to_module(path: Path, root: Path) -> str:
        rel = path.relative_to(root)
        return str(rel).replace(os.sep, ".").replace(".py", "")

    async def run(self, root_path: str = "."):
        self._running = True
        log.info("SelfDiscoveryEngine run loop started")
        while self._running:
            await self.scan(root_path)
            await asyncio.sleep(self.SCAN_INTERVAL)

    def stop(self):
        self._running = False
