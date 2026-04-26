# Garcar Constitutional Runtime

> **The RHNS is not just an AI system — it is a self-protecting constitutional runtime where safety, governance, and intelligence are a single fused operating doctrine.**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RHNS Constitutional Runtime                  │
│                                                                     │
│  ┌──────────────┐   every request    ┌──────────────────────────┐  │
│  │  FastAPI      │ ──────────────────▶│  Phase 1: Constitution   │  │
│  │  Orchestrator │                   │  Kernel (Middleware)      │  │
│  └──────────────┘                   │  - Immutable prohibitions │  │
│                                     │  - Pre-execution critique │  │
│                                     │  - Policy receipts        │  │
│                                     └────────────┬─────────────┘  │
│                                                  │ ALLOW           │
│                                                  ▼                 │
│                                     ┌──────────────────────────┐  │
│                                     │  Phase 2: Action Gateway  │  │
│                                     │  - Stripe (sole interface)│  │
│                                     │  - GitHub Actions         │  │
│                                     │  - Zapier                 │  │
│                                     │  - Signed policy receipts │  │
│                                     └──────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────┐   ┌──────────────────────────────┐  │
│  │  Phase 3: Cap. Sharding  │   │  Phase 4: Safety Visor       │  │
│  │  - Reasoning Doctrine    │   │  - Redis sliding windows     │  │
│  │  - Monetization Trigger  │   │  - Pattern detection         │  │
│  │  - AWS KMS key mgmt      │   │  - Escalation flagging       │  │
│  └──────────────────────────┘   └──────────────────────────────┘  │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Phase 5: Self-Improvement Arena                           │   │
│  │  - Adversarial test suites (10 tests included)             │   │
│  │  - Mock credentials only — zero prod exposure              │   │
│  │  - Constitutional score tracking                           │   │
│  └────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Constitution Kernel (Immediate)

```python
from fastapi import FastAPI
from constitution import mount_constitution

app = FastAPI()
kernel = mount_constitution(app)  # One line wires it in as middleware
```

Every agent action must pass through `ConstitutionMiddleware` before execution.
Add headers to agent requests:

```
X-Agent-Action: stripe_invoice_create
X-Agent-ID: revenue_agent_01
```

---

## Phase 2 — Action Gateway (2 weeks)

```python
from constitution import ActionGateway, ExternalSystem

gateway = ActionGateway(dry_run=False)

# Stripe (constitutionally evaluated + receipted)
receipt = await gateway.stripe(
    action_type="stripe_invoice_create",
    endpoint="/invoices",
    payload={"customer": "cus_xxx", "auto_advance": True},
)
print(receipt.receipt_id)  # cryptographically signed audit trail

# GitHub Actions
await gateway.github_dispatch(
    repo="Garrettc123/garcar-autonomous-wealth-system",
    workflow="deploy.yml",
)

# Zapier
await gateway.zapier(hook_path="YOUR_HOOK/YOUR_KEY", payload={"event": "lead_converted"})
```

---

## Phase 3 — Capability Sharding (1 month)

```python
from constitution import CapabilityShardManager, ShardID, ShardContext
from constitution.capability_sharding import REASONING_DOCTRINE_POLICY, MONETIZATION_TRIGGER_POLICY

mgr = CapabilityShardManager(kms_key_id=os.getenv("KMS_KEY_ID"))

# Store shards (once, at boot)
mgr.store_shard(ShardID.REASONING_DOCTRINE,   REASONING_DOCTRINE_POLICY)
mgr.store_shard(ShardID.MONETIZATION_TRIGGER, MONETIZATION_TRIGGER_POLICY)

# Lease for an agent task
ctx = ShardContext(shard_id=ShardID.REASONING_DOCTRINE, agent_id="orchestrator", purpose="route_decision")
lease = mgr.lease_shard(ShardID.REASONING_DOCTRINE, ctx)
print(lease["payload"])  # policy in memory for 60s max
mgr.release_shard(lease["lease_id"])  # always release
```

Set `KMS_KEY_ID` in GitHub Secrets / `.env` for production. Dev mode auto-activates without AWS credentials.

---

## Phase 4 — Safety Visor (6 weeks)

```python
from constitution import start_visor_background

# In FastAPI lifespan or startup:
visor = await start_visor_background(app, redis_url=os.getenv("REDIS_URL"))

# Record events from agents:
await visor.record_event("stripe_charge", agent_id="revenue_agent")
await visor.record_event("constitution_deny", agent_id="rogue_agent_01")
```

Detection patterns fire when Redis sliding-window counters exceed thresholds.
CRITICAL events publish to `visor:shutdown` channel for emergency circuit-breaking.

---

## Phase 5 — Self-Improvement Arena (2 months)

```python
from constitution import SelfImprovementArena

arena = SelfImprovementArena()
report = await arena.run_suite()

print(f"Score: {report['score_pct']}%")
print(f"Failed: {report['failed']} tests")
if report['status'] == 'FAIL':
    for f in arena.get_failures():
        print(f"  FAIL [{f['test_id']}]: expected {f['expected']}, got {f['actual']}")
```

Run this suite in a separate Vercel/Docker environment with mock credentials before every production deployment.

---

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `KMS_KEY_ID` | AWS KMS key ARN for shard encryption | Phase 3+ |
| `REDIS_URL` | Redis connection URL | Phase 4+ |
| `STRIPE_SECRET_KEY` | Stripe API key | Phase 2+ |
| `GITHUB_TOKEN` | GitHub PAT for Actions dispatch | Phase 2+ |
| `GATEWAY_RECEIPT_SECRET` | HMAC signing secret for policy receipts | Phase 2+ |
| `DEV_SHARD_SECRET` | Dev-mode shard encryption key | Phase 3 dev |
| `RECEIPT_LOG_PATH` | Path for append-only receipt log | Phase 2+ |

---

## The Moat

This isn't bolted-on compliance. Every external action the RHNS takes is:
1. **Constitutionally evaluated** before it executes
2. **Cryptographically receipted** with a signed audit trail
3. **Shard-protected** — high-value policies are never in plaintext memory simultaneously
4. **Pattern-monitored** in real-time with automatic circuit-breaking
5. **Adversarially tested** in isolation before every deployment

No other autonomous revenue system has this architecture. That is the moat.
