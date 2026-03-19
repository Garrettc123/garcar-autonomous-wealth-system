# Garcar Autonomous Wealth System — Copilot Instructions

## System Purpose
This repository is the core autonomous revenue engine for Garcar Enterprise.
All code changes must preserve zero-downtime operation of the 10-stage daily pipeline.

## Architecture
- **orchestrator_master.py** — master entry point, imports all 16 modules
- **revenue_compounding_loop.py** — 5x multiplier on every Stripe payment
- **performance_amplifier.py** — auto-tunes SSM params from S3 metrics history
- **system_monitor.py** — self-heals S3, Lambda, SES on every cycle
- **.github/workflows/master-revenue-trigger.yml** — 10-stage daily pipeline

## Coding Standards
- All Python must be compatible with Python 3.11+
- All AWS calls must use `boto3` with region from `AWS_REGION` env var
- All secrets must come from SSM `/garcar/` prefix or GitHub Actions secrets
- Never hardcode API keys, emails, or bucket names
- All new modules must be importable by `orchestrator_master.py` via `safe_import()`
- All workflow jobs must have `continue-on-error: true` on AWS auth steps
- All new workflows must support `workflow_call` for chaining

## Key Environment Variables
```
AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
OPENAI_API_KEY, STRIPE_SECRET_KEY, APOLLO_API_KEY
LINEAR_API_KEY, SES_SENDER_EMAIL, S3_BUCKET
GITHUB_TOKEN, GITHUB_REPOSITORY
```

## PR Guidelines
- PRs touching workflow files must keep the 10-stage chain intact
- PRs touching Python modules must not break `orchestrator_master.py` imports
- Always run `python -c "import <module>"` style check in CI before merge
- Ledger files (*.json) are auto-committed by bots — do not manually edit

## Self-Healing Rules
- If an SSM parameter is missing, fall back to env var, then skip gracefully
- If S3 bucket is missing, recreate it before failing
- If SES is unverified, resend verification — do not hard fail
- Lambda state != Active should trigger SNS/SES alert, not pipeline abort
