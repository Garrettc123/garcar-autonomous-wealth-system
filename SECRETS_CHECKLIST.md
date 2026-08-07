# 🔐 Garcar Enterprise — Auto Key Checklist

> **Authoritative list of every secret name:** [SECRETS.md](./SECRETS.md)
>
> Vault: https://github.com/Garrettc123/garcar-autonomous-wealth-system/settings/secrets/actions

Run `python setup_secrets.py` to auto-provision secrets from your `.env` into GitHub Actions.

## Quick Start

```bash
# 1. Install dependencies
pip install requests PyNaCl python-dotenv

# 2. Copy and fill your .env
cp .env.example .env
nano .env  # or code .env

# 3. Set your GitHub PAT
export GITHUB_TOKEN=ghp_yourPersonalAccessToken

# 4. Run auto-provisioner
python setup_secrets.py
```

---

## Secret Sources — Where to Get Each Key

### 💳 Stripe (Cashflow Workflow)
| Secret | Where |
|--------|-------|
| `STRIPE_SECRET_KEY` | [Stripe Dashboard → Developers → API Keys](https://dashboard.stripe.com/apikeys) |
| `STRIPE_PUBLISHABLE_KEY` | Same page |
| `STRIPE_WEBHOOK_SECRET` | [Stripe → Webhooks → Signing secret](https://dashboard.stripe.com/webhooks) |
| `STRIPE_PRICE_BASIC` / `PRO` / `ENTERPRISE` | [Stripe → Products](https://dashboard.stripe.com/products) |

### 📋 Linear
| Secret | Where |
|--------|-------|
| `LINEAR_API_KEY` | [Linear → Settings → API](https://linear.app/settings/api) |
| `LINEAR_TEAM_ID` | Team settings / URL |

### 🤖 OpenAI
| Secret | Where |
|--------|-------|
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |

### 🔍 Apollo.io
| Secret | Where |
|--------|-------|
| `APOLLO_API_KEY` | [Apollo → Integrations → API](https://app.apollo.io/#/settings/integrations/api) |

### 📧 Email / SMTP / SES
| Secret | Where |
|--------|-------|
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | Provider (Gmail app password, SendGrid, etc.) |
| `SES_SENDER_EMAIL` | Verified identity in AWS SES |

### 📱 Twilio (exact names used by workflows)
| Secret | Where |
|--------|-------|
| `TWILIO_ACCOUNT_SID` | [Twilio Console](https://console.twilio.com) |
| `TWILIO_AUTH_TOKEN` | Same |
| `TWILIO_FROM_NUMBER` | Twilio phone numbers |

### 📚 Notion
| Secret | Where |
|--------|-------|
| `NOTION_TOKEN` | [Notion integrations](https://www.notion.so/my-integrations) |

### ⚡ Redis / Railway
| Secret | Where |
|--------|-------|
| `REDIS_URL` | Railway Redis → Connect |
| `RAILWAY_TOKEN` | [Railway tokens](https://railway.app/account/tokens) |
| `RAILWAY_APP_URL` | Service public URL |

### 💙 HubSpot
| Secret | Where |
|--------|-------|
| `HUBSPOT_API_KEY` | HubSpot private apps |

### 🔑 GitHub PAT (cross-repo)
| Secret | Where |
|--------|-------|
| `GH_PAT` | Fine-grained PAT: `repo`, `workflow` |

### AWS (prefer OIDC)
```
OIDC_ROLE_ARN           → preferred long-term
AWS_ACCESS_KEY_ID       → bootstrap only, then delete
AWS_SECRET_ACCESS_KEY   → bootstrap only, then delete
AWS_REGION / AWS_ACCOUNT_ID / S3_BUCKET / LAMBDA_EXECUTION_ROLE_ARN / KMS_KEY_ID
```

---

## ✅ Readiness Check

After provisioning:

- **Secrets**: https://github.com/Garrettc123/garcar-autonomous-wealth-system/settings/secrets/actions  
- **Actions**: https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions  
- **Canonical names**: [SECRETS.md](./SECRETS.md)

Cron workflows arm as soon as their required secrets exist.
