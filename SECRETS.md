# Garcar Autonomous Wealth System — Secrets (Single Source of Truth)

**One vault. Everything else pulls from it.**

```
https://github.com/Garrettc123/garcar-autonomous-wealth-system/settings/secrets/actions
```

Set secrets **once** here. Workflows, AWS Secrets Manager (`garcar/all` via `secrets-bootstrap.yml`), and Railway consumers read from this store. Do not maintain parallel copies elsewhere.

Cross-repo payments secrets live in sibling vault:  
https://github.com/Garrettc123/garcar-payments/settings/secrets/actions  
(see that repo’s `SECRETS.md`)

---

## Canonical secrets (exact names)

### Core revenue
| Secret | Used by |
|--------|---------|
| `STRIPE_SECRET_KEY` | cashflow, lead-gen, orchestrator, stripe-health, alw, canyon |
| `STRIPE_PUBLISHABLE_KEY` | bootstrap → AWS |
| `STRIPE_WEBHOOK_SECRET` | cashflow, bootstrap |
| `STRIPE_PRICE_BASIC` | bootstrap / products |
| `STRIPE_PRICE_PRO` | bootstrap / products |
| `STRIPE_PRICE_ENTERPRISE` | bootstrap / products |

### Lead gen & outreach
| Secret | Used by |
|--------|---------|
| `APOLLO_API_KEY` | lead-gen, acquisition-loop, zero-touch |
| `OPENAI_API_KEY` | lead-gen, orchestrator, nurture |
| `HUBSPOT_API_KEY` | lead scoring |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | delivery, lead-gen |
| `SES_SENDER_EMAIL` | nurture, acquisition, bootstrap |
| `TWILIO_ACCOUNT_SID` | SMS outreach |
| `TWILIO_AUTH_TOKEN` | SMS outreach |
| `TWILIO_FROM_NUMBER` | SMS outreach |

### Ops & product
| Secret | Used by |
|--------|---------|
| `LINEAR_API_KEY` | almost all workflows |
| `LINEAR_TEAM_ID` | cashflow, bootstrap, zero-touch |
| `NOTION_TOKEN` | delivery, orchestrator, revenue reports |
| `REDIS_URL` | cashflow dashboard sync |
| `RAILWAY_TOKEN` | cashflow, deploy-railway |
| `RAILWAY_APP_URL` | deploy-railway health |
| `DASHBOARD_URL` | acquisition, nurture |
| `UPGRADE_URL` | acquisition, SMS |
| `TRIAL_URL` | SMS |
| `CALENDAR_URL` | SMS |
| `DASHBOARD_API_KEY` | bootstrap → AWS |
| `S3_BUCKET` | acquisition, bootstrap |

### AWS (optional path — prefer OIDC)
| Secret | Notes |
|--------|-------|
| `OIDC_ROLE_ARN` | Preferred. Zero long-lived keys. |
| `AWS_ACCESS_KEY_ID` | Bootstrap only; delete after OIDC works |
| `AWS_SECRET_ACCESS_KEY` | Bootstrap only |
| `AWS_REGION` | Default `us-east-1` |
| `AWS_ACCOUNT_ID` | Account number |
| `LAMBDA_EXECUTION_ROLE_ARN` | Lambda deploy |
| `KMS_KEY_ID` | Encryption |

### Cross-repo dispatch
| Secret | Notes |
|--------|-------|
| `GH_PAT` | Fine-grained PAT with `repo` + `workflow` for cross-repo `workflow_dispatch` |

---

## Naming rules

- Use **`TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER`** (not `TWILIO_SID` / `TWILIO_TOKEN` / `TWILIO_FROM`).
- Stripe price secrets in *this* repo are `STRIPE_PRICE_BASIC|PRO|ENTERPRISE`.  
  Payments repo uses `STRIPE_PRICE_AUDIT|DEALDESK|STARTER|PRO|AGENCY` — different catalog, same vault pattern.
- Prefer `OIDC_ROLE_ARN` over static AWS keys after first bootstrap.

---

## One-time activation

1. Add every secret you need at the link above.  
2. (Optional AWS) Run once:  
   https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions/workflows/secrets-bootstrap.yml  
   → pushes the bundle to AWS Secrets Manager `garcar/all`.  
3. (Optional OIDC) Run:  
   https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions/workflows/bootstrap-aws-keys.yml  
   then remove static AWS keys from GitHub.  
4. Arm cron: open any active workflow → **Run workflow**, or wait for schedule.

Local helper (fills GitHub from `.env`): `python setup_secrets.py` — see `SECRETS_CHECKLIST.md`.

---

## Active cron entry points

| Workflow | Schedule | Run link |
|----------|----------|----------|
| Cashflow | every 6h | [01-cashflow-automation.yml](https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions/workflows/01-cashflow-automation.yml) |
| Lead gen | Mon/Wed/Fri 9AM + daily 6PM | [02-lead-gen-sales.yml](https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions/workflows/02-lead-gen-sales.yml) |
| Master orchestrator | 6AM + 8PM | [05-master-orchestrator.yml](https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions/workflows/05-master-orchestrator.yml) |
| Watchdog v2 | hourly :30 | [garcar-watchdog-v2.yml](https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions/workflows/garcar-watchdog-v2.yml) |

Full Actions index: https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions
