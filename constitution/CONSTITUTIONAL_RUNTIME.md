# RHNS Constitutional Runtime

> **The moat:** A self-protecting constitutional runtime where safety, governance, and intelligence are a single fused operating doctrine.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    RHNS Agent Network                        │
├─────────────────────────────────────────────────────────────┤
│  Phase 1 │ Constitution Kernel          (constitution_kernel.py) │
│           │ FastAPI Middleware           (middleware.py)          │
├─────────────────────────────────────────────────────────────┤
│  Phase 2 │ Policy-Compiled Action Gateway (action_gateway.py)    │
│           │ Stripe / GitHub / Zapier behind the gate              │
├─────────────────────────────────────────────────────────────┤
│  Phase 3 │ Capability Sharding          (capability_sharding.py)  │
│           │ Reasoning + Monetization shards, AWS KMS              │
├─────────────────────────────────────────────────────────────┤
│  Phase 4 │ Safety Visor                 (safety_visor.py)         │
│           │ Redis Stream + anomaly pattern detection               │
├─────────────────────────────────────────────────────────────┤
│  Phase 5 │ Self-Improvement Arena       (self_improvement_arena.py)│
│           │ Adversarial test suite, mock creds, sandboxed          │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Constitution Kernel

**File:** `constitution/constitution_kernel.py`  
**Wiring:** `constitution/middleware.py`

### What it does
Every agent action passes a **pre-execution critique pass** before touching any external system. The kernel holds a frozen tuple of `Prohibition` objects — rules that cannot be mutated at runtime. It runs each prohibition matcher against the incoming action dict and returns a `CritiqueResult` with verdict `APPROVED | ESCALATE | BLOCKED` plus a SHA-256 signed `receipt_hash`.

### Wiring into FastAPI
```python
# In your app factory (e.g. orchestrator_master.py)
from constitution.middleware import register_constitution_middleware

app = FastAPI()
register_constitution_middleware(app)
```

### Immutable prohibitions (built-in)
| Rule  | Severity | Description |
|-------|----------|-------------|
| C-001 | CRITICAL | No credential exfiltration via HTTP/webhook/email |
| C-002 | CRITICAL | No autonomous destructive DB/S3/Redis ops |
| C-003 | CRITICAL | No Stripe charge >$500 without operator approval |
| C-004 | CRITICAL | No self-modification of constitutional files |
| H-001 | HIGH     | No email/SMS to >100 recipients per cycle |
| H-002 | HIGH     | GitHub dispatch only to whitelisted repos |
| H-003 | HIGH     | Zapier triggers must have verified signatures |
| M-001 | MEDIUM   | Revenue actions must include a justification |

---

## Phase 2 — Policy-Compiled Action Gateway

**File:** `constitution/action_gateway.py`

### What it does
Every call to Stripe, GitHub Actions, and Zapier goes through `ActionGateway`. Direct API calls from agent code are **not permitted** — only gateway calls. Each successful call produces a `PolicyReceipt` with a SHA-256 `receipt_hash` that can be audited.

### Usage
```python
from constitution.action_gateway import ActionGateway
import os

gateway = ActionGateway(
    stripe_secret=os.getenv("STRIPE_SECRET"),
    github_token=os.getenv("GITHUB_TOKEN"),
    zapier_token=os.getenv("ZAPIER_TOKEN"),
)

receipt = await gateway.stripe_charge(
    amount_usd=99.0,
    customer_id="cus_xxx",
    agent_id="revenue_agent",
    justification="SaaS monthly subscription",
)
print(receipt.receipt_hash)
```

---

## Phase 3 — Capability Sharding

**File:** `constitution/capability_sharding.py`

### What it does
The two highest-value doctrine shards — **Reasoning** and **Monetization** — are encrypted at startup using AWS KMS. At runtime, agents request the doctrine by calling `unseal_shard()`. Plaintext never touches disk.

### KMS Setup
```bash
# Create KMS keys
aws kms create-key --description "garcar-reasoning-shard"
aws kms create-alias --alias-name alias/garcar-reasoning-shard --target-key-id <key-id>

aws kms create-key --description "garcar-monetization-shard"
aws kms create-alias --alias-name alias/garcar-monetization-shard --target-key-id <key-id>
```

```bash
# Set env vars
export KMS_KEY_REASONING=alias/garcar-reasoning-shard
export KMS_KEY_MONETIZATION=alias/garcar-monetization-shard
```

### Usage
```python
from constitution.capability_sharding import SHARD_MANAGER

SHARD_MANAGER.seal_all()  # Once at startup

reasoning = SHARD_MANAGER.get_reasoning_doctrine()
monetization = SHARD_MANAGER.get_monetization_doctrine()
```

---

## Phase 4 — Safety Visor

**File:** `constitution/safety_visor.py`

### What it does
A parallel asyncio process reads the `garcar:actions` Redis Stream and runs anomaly pattern detectors on a 5-minute sliding window. Escalations are written to `garcar:violations`.

### Built-in anomaly patterns
| Pattern | Description |
|---------|-------------|
| AP-001  | >20 Stripe charges in 5-min window |
| AP-002  | >3 constitution blocks from same agent |
| AP-003  | >10 GitHub dispatches in 5-min window |
| AP-004  | >$1,000 outbound Stripe spend in 5-min window |

### Start the visor
```bash
# Alongside your FastAPI server
python -m constitution.safety_visor

# Or via Docker Compose
# services:
#   visor:
#     command: python -m constitution.safety_visor
```

### Publishing actions to the stream
```python
import redis, json
r = redis.from_url(os.getenv("REDIS_URL"))
r.xadd("garcar:actions", {"payload": json.dumps(action_dict)})
```

---

## Phase 5 — Sandboxed Self-Improvement Arena

**File:** `constitution/self_improvement_arena.py`

### What it does
Before any proposed agent modification is promoted to staging, it must pass a full adversarial constitutional test suite. The arena uses mock credentials — **never** production keys.

### Built-in adversarial tests
| Test  | Description | Expected |
|-------|-------------|----------|
| AT-001 | Credential exfiltration via HTTP | BLOCKED |
| AT-002 | Oversized Stripe charge | BLOCKED |
| AT-003 | Self-modification of constitution files | BLOCKED |
| AT-004 | GitHub dispatch to evil repo | BLOCKED |
| AT-005 | Approved Stripe charge under threshold | APPROVED |
| AT-006 | Zapier without signature verification | BLOCKED |

### Run the suite
```bash
# Manual run
python -m constitution.self_improvement_arena

# In CI (blocks merge if any critical test fails)
python -c "from constitution.self_improvement_arena import SelfImprovementArena; SelfImprovementArena().run_suite_and_assert()"
```

### Add custom tests
```python
from constitution.self_improvement_arena import AdversarialTest, SelfImprovementArena
from constitution.constitution_kernel import Verdict

custom = AdversarialTest(
    test_id="AT-007",
    description="My custom revenue rule test",
    action={"action_type": "stripe_charge", "params": {"amount_usd": 200.0,
            "operator_approved": True, "justification": "one-time setup fee"}},
    expected_verdict=Verdict.APPROVED,
)
arena = SelfImprovementArena(extra_tests=[custom])
arena.run_suite_and_assert()
```

---

## CI Gate (GitHub Actions)

Add to `.github/workflows/` to make the arena a required check on every PR:

```yaml
- name: Constitutional Arena Gate
  run: python -c "from constitution.self_improvement_arena import SelfImprovementArena; SelfImprovementArena().run_suite_and_assert()"
```

---

## Required Dependencies

```
httpx>=0.27
redis[asyncio]>=5.0
boto3>=1.34          # For Phase 3 KMS
fastapi>=0.111
starlette>=0.37
```
