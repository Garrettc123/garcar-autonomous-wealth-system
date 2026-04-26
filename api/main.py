"""Garcar API — FastAPI gateway to the RHNS + Revenue systems
Endpoints:
  GET  /health          — system health snapshot
  GET  /network         — full RHNS topology
  POST /task            — route a task to the network
  GET  /revenue         — revenue loop summary
  GET  /nwu             — NWU portfolio
  GET  /discoveries     — breakthrough discoveries log
  POST /leads           — inject leads into revenue loop
  GET  /capabilities    — full capability registry
"""
from __future__ import annotations
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
except ImportError:
    raise ImportError("pip install fastapi uvicorn")

from core.rhns_engine import rhns
from core.nwu_protocol import nwu
from core.self_discovery_engine import SelfDiscoveryEngine
from core.autonomous_revenue_loop import AutonomousRevenueLoop

log = logging.getLogger("api")

app = FastAPI(
    title="Garcar Enterprise API",
    description="Autonomous Revenue & Intelligence Platform",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

discovery = SelfDiscoveryEngine(rhns=rhns)
revenue = AutonomousRevenueLoop(nwu=nwu, rhns=rhns)


class TaskRequest(BaseModel):
    capability: str
    payload: Dict[str, Any] = {}


class LeadBatch(BaseModel):
    leads: List[Dict[str, Any]]


@app.get("/health")
async def health():
    snapshot = await rhns.discover()
    return {
        "status": "operational",
        "uptime": time.time(),
        "network_health": snapshot["network_health"],
        "active_nodes": snapshot["active_nodes"],
        "total_revenue": revenue.summary["total_revenue"]
    }


@app.get("/network")
async def network():
    return await rhns.discover()


@app.post("/task")
async def route_task(req: TaskRequest):
    task_id = await rhns.route_task(req.capability, req.payload)
    if not task_id:
        raise HTTPException(404, f"No node available for capability: {req.capability}")
    return {"task_id": task_id, "status": "queued"}


@app.get("/revenue")
async def get_revenue():
    return revenue.summary


@app.get("/nwu")
async def get_nwu():
    return nwu.portfolio()


@app.get("/discoveries")
async def get_discoveries():
    return {"discoveries": discovery.discoveries[-50:]}


@app.post("/leads")
async def inject_leads(batch: LeadBatch, background_tasks: BackgroundTasks):
    background_tasks.add_task(revenue.run_cycle, batch.leads)
    return {"status": "processing", "count": len(batch.leads)}


@app.get("/capabilities")
async def get_capabilities():
    return {
        "total": len(discovery.registry),
        "capabilities": [
            {"name": r.name, "kind": r.kind, "status": r.status,
             "breakthrough_score": r.breakthrough_score}
            for r in sorted(discovery.registry.values(),
                            key=lambda x: x.breakthrough_score, reverse=True)[:100]
        ]
    }


@app.on_event("startup")
async def startup():
    log.info("API startup — scanning capabilities")
    asyncio.create_task(discovery.scan("."))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
