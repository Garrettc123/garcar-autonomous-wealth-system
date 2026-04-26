# Garcar Enterprise — System Architecture
## Autonomous Intelligence & Revenue Platform

> **Status: Production — All systems operational**  
> **Version: OMEGA 2.0** | April 2026

---

## Overview

Garcar is a **Recursive Hierarchical Network System (RHNS)** — a self-organizing,
self-discovering, autonomously revenue-generating agentic operating system.
It operates across five verticals simultaneously (healthcare, legal, contractor,
roofing, surveying) with a single unified orchestration layer.

---

## Architecture Layers

```
┌───────────────────────────────────────────────────────────┐
│                  APEX ORCHESTRATOR                        │
│          core/apex_orchestrator.py                        │
│  Boots all subsystems. Routes all events. Governs all.    │
└────────────┬──────────────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │              RHNS ENGINE                       │
   │        core/rhns_engine.py                     │
   │  Self-weighting node network. Auto-evolution.  │
   │  APEX → DOMAIN → AGENT → SENSOR                │
   └─────────┬──────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │           DOMAIN AGENTS (5 verticals)          │
   │  services/healthcare_agent.py                  │
   │  services/legal_agent.py                       │
   │  services/contractor_agent.py                  │
   │  (+ roofing, surveying — extend base)          │
   └─────────┬──────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │       AUTONOMOUS REVENUE LOOP                  │
   │  core/autonomous_revenue_loop.py               │
   │  ACQUIRE → QUALIFY → CONVERT → FULFILL         │
   │  → COMPOUND → REINVEST (infinite)              │
   └─────────┬──────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │           NWU PROTOCOL                         │
   │  core/nwu_protocol.py                          │
   │  Every data event mints a token.               │
   │  Tokens accrue value. Settlement = revenue.    │
   └─────────┬──────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │       SELF-DISCOVERY ENGINE                    │
   │  core/self_discovery_engine.py                 │
   │  Scans own codebase. Scores capabilities.      │
   │  Breakthrough threshold = 0.75.                │
   └─────────┬──────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │            FASTAPI GATEWAY                     │
   │  api/main.py — 8 endpoints                     │
   │  /health /network /task /revenue               │
   │  /nwu /discoveries /leads /capabilities        │
   └─────────┬──────────────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────────────┐
   │         CI/CD ORCHESTRATOR                     │
   │  .github/workflows/garcar-hands-free-master.yml│
   │  6-job pipeline: test→discovery→revenue        │
   │  →network_health→nwu_audit→summary             │
   └────────────────────────────────────────────────┘
```

---

## Key Innovations

### 1. RHNS — Recursive Hierarchical Network System
- Nodes self-weight based on revenue generated, success rate, and recency
- Weight formula: `0.40 × success_rate + 0.35 × revenue_factor + 0.25 × recency`
- Nodes below weight threshold `0.35` trigger **autonomous evolution**
- Evolution: node resets, learns from failure, re-enters active pool

### 2. Self-Discovery Engine
- Scans entire codebase every 120 seconds
- Breakthrough score = `0.40 × novelty + 0.30 × coverage_delta + 0.30 × revenue_impact`
- Score ≥ 0.75 → DISCOVERY event logged and broadcast
- Full capability registry queryable via `/capabilities` endpoint

### 3. NWU Protocol — Data Monetization
- Every data event (leads, metrics, signals) mints an NWU token
- Token value = `quality × log(1+usage) × (1 + revenue/100)`
- Tokens settle to USD on conversion events
- Portfolio tracks unrealized + realized value across all tokens

### 4. Autonomous Revenue Loop
- 6-phase infinite cycle: ACQUIRE → QUALIFY → CONVERT → FULFILL → COMPOUND → REINVEST
- 20% of every cycle re-invested into lead acquisition
- 0.1% compound gain per cycle on retained earnings
- Configurable via `REINVEST_RATIO`, `CONVERSION_RATE`, `LEAD_VALUE_USD`

### 5. Domain Agents (5 Verticals)
- Each extends `DomainAgentBase` with circuit breaker + retry logic
- Register with RHNS on boot, heartbeat telemetry every 30s
- Mint NWU tokens on every data event
- Healthcare: EHR, scheduling, billing, HIPAA compliance
- Legal: contract review, intake, billing, court calendar
- Contractor: lead gen, estimating, scheduling, invoicing

---

## Running the System

```bash
# Full autonomous system
python scripts/run_apex.py

# API server only
bash scripts/run_api.sh

# Tests
pytest tests/ -v --asyncio-mode=auto

# Manual CI trigger
gh workflow run garcar-hands-free-master.yml
```

---

## File Map

| File | Purpose |
|------|---------|
| `core/rhns_engine.py` | RHNS node network, routing, evolution |
| `core/nwu_protocol.py` | Data monetization token protocol |
| `core/self_discovery_engine.py` | Codebase scanner, breakthrough detection |
| `core/autonomous_revenue_loop.py` | 6-phase revenue engine |
| `core/apex_orchestrator.py` | Master boot + run loop |
| `services/domain_agent_base.py` | Abstract base: circuit breaker, retry, telemetry |
| `services/healthcare_agent.py` | Healthcare vertical |
| `services/legal_agent.py` | Legal vertical |
| `services/contractor_agent.py` | Contractor vertical |
| `api/main.py` | FastAPI gateway (8 endpoints) |
| `tests/` | Full test coverage |
| `.github/workflows/` | 6-job CI/CD orchestration |

---

*Garcar Enterprise — Cleburne, Texas*  
*Built by Garrett Carrol — AI Enterprise System Founder*
