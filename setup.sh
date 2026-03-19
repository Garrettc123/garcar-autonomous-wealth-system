#!/usr/bin/env bash
# =============================================================
#  GARCAR ONE-SHOT SETUP — Run this ONCE from Termux or any terminal
#  Prompts for your 4 API keys, stores to AWS SSM,
#  syncs to GitHub Actions, triggers bootstrap workflow.
#  After this runs: NEVER touch secrets again.
# =============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

REPO="Garrettc123/garcar-autonomous-wealth-system"
REGION="us-east-1"
GH_API="https://api.github.com"

echo ""
echo -e "${BOLD}${CYAN}============================================================${RESET}"
echo -e "${BOLD}${CYAN}  GARCAR ZERO-TOUCH SETUP${RESET}"
echo -e "${CYAN}  One-time run. Never touch secrets again after this.${RESET}"
echo -e "${BOLD}${CYAN}============================================================${RESET}"
echo ""

# ── 0. Check dependencies ────────────────────────────────────
check_dep() {
  if ! command -v "$1" &>/dev/null; then
    echo -e "${RED}Missing: $1. Installing...${RESET}"
    case "$1" in
      aws)   pip install awscli -q || pip3 install awscli -q ;;
      gh)    echo -e "${YELLOW}Install GitHub CLI: https://cli.github.com${RESET}"; exit 1 ;;
      jq)    apt-get install -y jq 2>/dev/null || pkg install jq -y 2>/dev/null || true ;;
      python3) echo -e "${RED}python3 required${RESET}"; exit 1 ;;
      curl)  apt-get install -y curl 2>/dev/null || pkg install curl -y 2>/dev/null ;;
    esac
  fi
}
check_dep aws
check_dep python3
check_dep curl
check_dep jq

# ── 1. AWS credentials check ─────────────────────────────────
echo -e "${BOLD}Step 1/5 — AWS Credentials${RESET}"
if ! aws sts get-caller-identity --region $REGION &>/dev/null; then
  echo -e "${YELLOW}AWS credentials not configured. Running aws configure...${RESET}"
  echo -e "  Get keys from: https://console.aws.amazon.com/iam/home#/security_credentials"
  aws configure set region $REGION
  read -rp "  AWS Access Key ID: " aws_id
  read -rsp "  AWS Secret Access Key: " aws_secret; echo
  aws configure set aws_access_key_id "$aws_id"
  aws configure set aws_secret_access_key "$aws_secret"
  aws configure set region $REGION
  echo -e "${GREEN}  AWS configured.${RESET}"
else
  ACCT=$(aws sts get-caller-identity --query Account --output text --region $REGION)
  echo -e "${GREEN}  AWS already configured. Account: $ACCT${RESET}"
fi

# ── 2. GitHub token check ─────────────────────────────────────
echo ""
echo -e "${BOLD}Step 2/5 — GitHub Token${RESET}"
if [ -z "$GITHUB_TOKEN" ]; then
  echo -e "  Get a token (needs repo + secrets scope) from:"
  echo -e "  ${CYAN}https://github.com/settings/tokens/new?scopes=repo,secrets${RESET}"
  read -rsp "  GitHub Personal Access Token: " GH_TOKEN; echo
  export GITHUB_TOKEN="$GH_TOKEN"
else
  echo -e "${GREEN}  GITHUB_TOKEN already set.${RESET}"
  GH_TOKEN="$GITHUB_TOKEN"
fi

# Verify token works
GH_USER=$(curl -sf -H "Authorization: token $GH_TOKEN" \
  "$GH_API/user" | jq -r .login 2>/dev/null || echo "unknown")
echo -e "${GREEN}  GitHub authenticated as: $GH_USER${RESET}"

# ── 3. Collect API keys ───────────────────────────────────────
echo ""
echo -e "${BOLD}Step 3/5 — Revenue API Keys${RESET}"
echo -e "  Enter each key. Input is hidden. Press Enter to skip if already in SSM."
echo ""

prompt_key() {
  local KEY="$1" HINT="$2" URL="$3"
  # Check if already in SSM
  EXISTING=$(aws ssm get-parameter --name "/garcar/$KEY" \
    --with-decryption --query Parameter.Value \
    --output text --region $REGION 2>/dev/null || echo "")
  if [ -n "$EXISTING" ]; then
    echo -e "  ${GREEN}$KEY already in SSM — skipping.${RESET}"
    return
  fi
  echo -e "  ${CYAN}$KEY${RESET} — $HINT"
  echo -e "  Get it: ${URL}"
  read -rsp "  Value (hidden): " VAL; echo
  if [ -n "$VAL" ]; then
    aws ssm put-parameter \
      --name "/garcar/$KEY" \
      --value "$VAL" \
      --type SecureString \
      --overwrite \
      --region $REGION \
      --description "Garcar auto-provisioned $(date -u +%Y-%m-%d)" \
      > /dev/null
    echo -e "  ${GREEN}Stored /garcar/$KEY in SSM.${RESET}"
  else
    echo -e "  ${YELLOW}Skipped $KEY.${RESET}"
  fi
  echo ""
}

prompt_key "STRIPE_SECRET_KEY" \
  "Stripe live secret key (starts with sk_live_)" \
  "https://dashboard.stripe.com/apikeys"

prompt_key "STRIPE_WEBHOOK_SECRET" \
  "Stripe webhook signing secret (starts with whsec_)" \
  "https://dashboard.stripe.com/webhooks — create endpoint pointing to your Lambda URL"

prompt_key "APOLLO_API_KEY" \
  "Apollo.io API key for lead generation" \
  "https://app.apollo.io/#/settings/integrations/api"

prompt_key "OPENAI_API_KEY" \
  "OpenAI API key (starts with sk-)" \
  "https://platform.openai.com/api-keys"

prompt_key "STRIPE_PRICE_PRO" \
  "Stripe Price ID for Pro plan (starts with price_)" \
  "https://dashboard.stripe.com/products — create a recurring product"

# ── 4. Push static AWS keys to GitHub for bootstrap ──────────
echo ""
echo -e "${BOLD}Step 4/5 — Push bootstrap AWS keys to GitHub Secrets${RESET}"
echo -e "  ${YELLOW}These will be auto-deleted after OIDC role is created.${RESET}"

# Get repo public key for encryption
PK_JSON=$(curl -sf \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "$GH_API/repos/$REPO/actions/secrets/public-key")
PK_KEY=$(echo "$PK_JSON" | jq -r .key)
PK_ID=$(echo "$PK_JSON"  | jq -r .key_id)

# Encrypt + push a secret to GitHub
push_gh_secret() {
  local NAME="$1" VALUE="$2"
  if [ -z "$VALUE" ]; then return; fi
  ENCRYPTED=$(python3 -c "
import base64, sys
from nacl import encoding, public
pub = public.PublicKey('$PK_KEY'.encode(), encoding.Base64Encoder())
box = public.SealedBox(pub)
enc = base64.b64encode(box.encrypt('$VALUE'.encode())).decode()
print(enc)
" 2>/dev/null)
  if [ -z "$ENCRYPTED" ]; then
    echo -e "  ${YELLOW}pynacl not found — installing...${RESET}"
    pip install pynacl -q
    ENCRYPTED=$(python3 -c "
import base64
from nacl import encoding, public
pub = public.PublicKey('$PK_KEY'.encode(), encoding.Base64Encoder())
box = public.SealedBox(pub)
enc = base64.b64encode(box.encrypt('$VALUE'.encode())).decode()
print(enc)
")
  fi
  STATUS=$(curl -sf -o /dev/null -w "%{http_code}" \
    -X PUT \
    -H "Authorization: token $GH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$GH_API/repos/$REPO/actions/secrets/$NAME" \
    -d "{\"encrypted_value\":\"$ENCRYPTED\",\"key_id\":\"$PK_ID\"}")
  if [ "$STATUS" = "201" ] || [ "$STATUS" = "204" ]; then
    echo -e "  ${GREEN}GitHub secret set: $NAME${RESET}"
  else
    echo -e "  ${RED}Failed to set $NAME (HTTP $STATUS)${RESET}"
  fi
}

# Push AWS creds for one-time bootstrap
AWS_ID=$(aws configure get aws_access_key_id)
AWS_SECRET=$(aws configure get aws_secret_access_key)
AWS_ACCT=$(aws sts get-caller-identity --query Account --output text --region $REGION 2>/dev/null || echo "")

push_gh_secret "AWS_ACCESS_KEY_ID"     "$AWS_ID"
push_gh_secret "AWS_SECRET_ACCESS_KEY" "$AWS_SECRET"
push_gh_secret "AWS_REGION"            "$REGION"
push_gh_secret "AWS_ACCOUNT_ID"        "$AWS_ACCT"

# ── 5. Trigger bootstrap workflow ────────────────────────────
echo ""
echo -e "${BOLD}Step 5/5 — Trigger Bootstrap Workflow${RESET}"
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" \
  -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "$GH_API/repos/$REPO/actions/workflows/bootstrap-aws-keys.yml/dispatches" \
  -d '{"ref":"main"}')

if [ "$HTTP" = "204" ]; then
  echo -e "  ${GREEN}Bootstrap workflow triggered!${RESET}"
else
  echo -e "  ${YELLOW}Trigger returned HTTP $HTTP — check Actions tab manually.${RESET}"
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo -e "${BOLD}${GREEN}  SETUP COMPLETE${RESET}"
echo -e "${GREEN}  The bootstrap workflow is running in GitHub Actions now.${RESET}"
echo -e "${GREEN}  It will:${RESET}"
echo -e "${GREEN}    1. Create OIDC role (no static AWS keys ever again)${RESET}"
echo -e "${GREEN}    2. Sync all SSM keys → GitHub Actions secrets${RESET}"
echo -e "${GREEN}    3. Provision S3 bucket, SES, Lambda roles${RESET}"
echo -e "${GREEN}${RESET}"
echo -e "${GREEN}  Watch it: https://github.com/$REPO/actions${RESET}"
echo -e "${GREEN}${RESET}"
echo -e "${GREEN}  After it completes: delete AWS_ACCESS_KEY_ID and${RESET}"
echo -e "${GREEN}  AWS_SECRET_ACCESS_KEY from GitHub Secrets.${RESET}"
echo -e "${GREEN}  From then on, everything is 100% automated forever.${RESET}"
echo -e "${BOLD}${GREEN}============================================================${RESET}"
echo ""
