# 🔐 Garcar Enterprise — Auto Key Checklist

> Run `python setup_secrets.py` to auto-provision all secrets from your `.env` into GitHub Actions.

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
| `STRIPE_WEBHOOK_SECRET` | [Stripe → Webhooks → your endpoint → Signing secret](https://dashboard.stripe.com/webhooks) |
| `STRIPE_PRICE_BASIC/PRO/ENTERPRISE` | [Stripe → Products → your product → Price ID](https://dashboard.stripe.com/products) |

### 📋 Linear (All Workflows)
| Secret | Where |
|--------|-------|
| `LINEAR_API_KEY` | [Linear → Settings → API → Personal API Keys](https://linear.app/settings/api) |
| `LINEAR_TEAM_ID` | Linear URL: `linear.app/[team-name]` — or Settings → General |

### 🤖 OpenAI (Lead Gen + Orchestrator)
| Secret | Where |
|--------|-------|
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |

### 🔍 Apollo.io (Lead Gen)
| Secret | Where |
|--------|-------|
| `APOLLO_API_KEY` | [Apollo → Settings → Integrations → API](https://app.apollo.io/#/settings/integrations/api) |

### 📧 Email / SMTP
| Secret | Where |
|--------|-------|
| `SMTP_HOST` | Your provider (e.g. `smtp.gmail.com`, `smtp.sendgrid.net`) |
| `SMTP_USER` | Your sender email |
| `SMTP_PASS` | App password (Gmail) or SendGrid API key |

> **Gmail users:** Enable 2FA → [Create App Password](https://myaccount.google.com/apppasswords). Use that as `SMTP_PASS`.

### 📱 Twilio (SMS Outreach)
| Secret | Where |
|--------|-------|
| `TWILIO_SID` | [Twilio Console → Account Info](https://console.twilio.com) |
| `TWILIO_TOKEN` | Same page |
| `TWILIO_FROM` | Twilio → Phone Numbers → your number |

### 📚 Notion (Delivery + Revenue Reports)
| Secret | Where |
|--------|-------|
| `NOTION_TOKEN` | [Notion → Settings → Connections → Develop or manage integrations](https://www.notion.so/my-integrations) |

### ⚡ Redis (Dashboard Sync)
| Secret | Where |
|--------|-------|
| `REDIS_URL` | [Railway → your Redis service → Connect → copy `REDIS_URL`](https://railway.app) |

### 🚂 Railway (Webhook Server)
| Secret | Where |
|--------|-------|
| `RAILWAY_TOKEN` | [Railway → Account Settings → Tokens](https://railway.app/account/tokens) |

### 💙 HubSpot (Lead Scoring)
| Secret | Where |
|--------|-------|
| `HUBSPOT_API_KEY` | [HubSpot → Settings → Account Setup → Integrations → Private Apps](https://app.hubspot.com/developer-docs/api) |

### 🔑 GitHub PAT (Cross-repo Triggers)
| Secret | Where |
|--------|-------|
| `GH_PAT` | [GitHub → Settings → Developer settings → Personal access tokens → Fine-grained](https://github.com/settings/tokens) |

> Required scopes: `repo`, `workflow`, `admin:repo_hook`

---

## AWS (Optional — for S3 + Lambda features)
```
AWS_ACCESS_KEY_ID     → AWS Console → IAM → Users → your user → Security credentials
AWS_SECRET_ACCESS_KEY → Same page
AWS_REGION            → us-east-1 (or your region)
```

---

## ✅ Readiness Check

After running `setup_secrets.py`, visit:
- **Secrets**: https://github.com/Garrettc123/garcar-autonomous-wealth-system/settings/secrets/actions
- **Actions**: https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions

All 5 workflows arm the moment their required secrets are present.
