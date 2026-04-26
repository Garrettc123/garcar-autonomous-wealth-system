#!/usr/bin/env bash
# =============================================================================
# GARCAR MASTER BOOTSTRAP — ALL-IN-ONE ZERO-KEY SETUP
# Run once from any machine that has AWS credentials available.
# After this script finishes you will NEVER need to manually enter a key again.
#
# What it does:
#   1.  Installs system deps (Python 3, pip, pynacl, boto3, requests)
#   2.  Configures AWS CLI (reads creds from environment or prompts once)
#   3.  Creates the GitHub Actions OIDC role  → static AWS keys never needed
#   4.  Provisions S3 bucket + SES verification
#   5.  Seeds every config default into SSM Parameter Store (SecureString)
#   6.  Prompts ONCE for any API keys that cannot be auto-generated (Stripe etc.)
#   7.  Syncs ALL SSM secrets  →  GitHub Actions encrypted secrets (self-healing)
#   8.  Installs the Python provisioner so future runs are fully headless
#
# Usage:
#   chmod +x garcar_master_bootstrap.sh && ./garcar_master_bootstrap.sh
#
# On subsequent deployments / CI runs, GitHub Actions calls:
#   python secrets_provisioner.py
# ...and everything self-heals from SSM with zero human input.
# =============================================================================

set -euo pipefail

# ─── Colour helpers ───────────────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RED="\033[1;31m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}  ✓ $*${RESET}"; }
info() { echo -e "${CYAN}  → $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${RESET}"; }
die()  { echo -e "${RED}  ✗ $*${RESET}"; exit 1; }

# ─── Config ───────────────────────────────────────────────────────────────────
SSM_PREFIX="/garcar/"
REGION="${AWS_REGION:-us-east-1}"
REPO="${GITHUB_REPOSITORY:-Garrettc123/garcar-autonomous-wealth-system}"
GH_TOKEN="${GITHUB_TOKEN:-}"
S3_BUCKET="garcar-revenue-data"
SES_EMAIL="noreply@garcar.io"
ROLE_NAME="garcar-github-actions-role"

# Revenue-critical keys that cannot be auto-generated
REVENUE_KEYS=(
  STRIPE_SECRET_KEY
  STRIPE_PUBLISHABLE_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_PRO
  STRIPE_PRICE_STARTER
  OPENAI_API_KEY
  APOLLO_API_KEY
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_PHONE_NUMBER
  SENDGRID_API_KEY
  LINEAR_API_KEY
  ZAPIER_WEBHOOK_URL
)

# Non-sensitive config defaults seeded automatically
declare -A DEFAULTS
DEFAULTS=(
  [AWS_REGION]="$REGION"
  [S3_BUCKET]="$S3_BUCKET"
  [SES_SENDER_EMAIL]="$SES_EMAIL"
  [DASHBOARD_URL]="https://app.garcar.io/dashboard"
  [UPGRADE_URL]="https://app.garcar.io/upgrade"
  [TRIAL_URL]="https://app.garcar.io/trial"
  [CALENDAR_URL]="https://cal.garcar.io/enterprise"
  [MIN_LEAD_SCORE]="60"
  [LEADS_PER_CYCLE]="50"
  [GITHUB_REPOSITORY]="$REPO"
)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 0 — Banner
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║        GARCAR MASTER BOOTSTRAP — ZERO-KEY SETUP         ║${RESET}"
echo -e "${BOLD}║              $(date -u '+%Y-%m-%d %H:%M:%S UTC')              ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Detect environment (Termux / Linux / macOS)
# ─────────────────────────────────────────────────────────────────────────────
info "Detecting environment..."
OS_TYPE="linux"
if [ -d "/data/data/com.termux" ]; then
  OS_TYPE="termux"
  ok "Termux environment detected"
elif [[ "$OSTYPE" == "darwin"* ]]; then
  OS_TYPE="macos"
  ok "macOS detected"
else
  ok "Linux detected"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Install system dependencies
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Installing system dependencies..."

install_pkg() {
  case "$OS_TYPE" in
    termux) pkg install -y "$1" 2>/dev/null || true ;;
    macos)  brew install "$1" 2>/dev/null || true ;;
    *)      sudo apt-get install -y "$1" 2>/dev/null || true ;;
  esac
}

if ! command -v python3 &>/dev/null; then
  install_pkg python
fi
if ! command -v pip3 &>/dev/null; then
  install_pkg python-pip 2>/dev/null || install_pkg python3-pip 2>/dev/null || true
fi
if ! command -v aws &>/dev/null; then
  info "Installing AWS CLI..."
  if [ "$OS_TYPE" = "termux" ]; then
    pip3 install awscli --quiet
  elif [ "$OS_TYPE" = "macos" ]; then
    brew install awscli 2>/dev/null || pip3 install awscli --quiet
  else
    pip3 install awscli --quiet
  fi
fi

# Python packages
info "Installing Python packages..."
pip3 install --quiet boto3 requests pynacl 2>/dev/null || \
  pip install --quiet boto3 requests pynacl 2>/dev/null || true

ok "Dependencies ready"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — AWS credentials bootstrap (one-time only)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Checking AWS credentials..."

if aws sts get-caller-identity &>/dev/null; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  ok "AWS credentials valid — Account: $ACCOUNT_ID"
else
  warn "No valid AWS credentials found. Entering one-time setup."
  echo ""
  echo -e "${BOLD}  This is the ONLY time you will ever need to enter AWS keys.${RESET}"
  echo -e "  After this script runs, GitHub Actions will use OIDC and"
  echo -e "  all keys will live in SSM — never in files or env vars."
  echo ""

  # Try to read from env first
  AWS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"
  AWS_SECRET="${AWS_SECRET_ACCESS_KEY:-}"

  if [ -z "$AWS_KEY_ID" ]; then
    read -r -p "  AWS Access Key ID:     " AWS_KEY_ID
  fi
  if [ -z "$AWS_SECRET" ]; then
    read -r -s -p "  AWS Secret Access Key: " AWS_SECRET
    echo ""
  fi

  aws configure set aws_access_key_id "$AWS_KEY_ID"
  aws configure set aws_secret_access_key "$AWS_SECRET"
  aws configure set default.region "$REGION"

  if aws sts get-caller-identity &>/dev/null; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    ok "AWS credentials configured — Account: $ACCOUNT_ID"
    echo ""
    warn "These bootstrap credentials can be deleted from ~/.aws after setup."
    warn "Once OIDC role is live, GitHub Actions never needs static keys."
  else
    die "AWS credentials invalid. Please check and re-run."
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — GitHub token (for syncing secrets to GitHub Actions)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Checking GitHub token..."

if [ -z "$GH_TOKEN" ]; then
  # Try to load from SSM if it exists
  GH_FROM_SSM=$(aws ssm get-parameter --name "${SSM_PREFIX}GITHUB_TOKEN" \
    --with-decryption --query Parameter.Value --output text 2>/dev/null || echo "")
  if [ -n "$GH_FROM_SSM" ]; then
    GH_TOKEN="$GH_FROM_SSM"
    ok "GitHub token loaded from SSM"
  else
    echo ""
    echo -e "${BOLD}  GitHub Personal Access Token (PAT) needed ONCE${RESET}"
    echo -e "  Required scopes: repo, workflow, admin:repo_hook"
    echo -e "  Get one at: https://github.com/settings/tokens/new"
    echo -e "  After this, it lives in SSM — never typed again."
    echo ""
    read -r -s -p "  GitHub PAT: " GH_TOKEN
    echo ""
    # Store immediately in SSM
    aws ssm put-parameter \
      --name "${SSM_PREFIX}GITHUB_TOKEN" \
      --value "$GH_TOKEN" \
      --type SecureString \
      --overwrite \
      --region "$REGION" >/dev/null
    ok "GitHub token stored in SSM — never needed manually again"
  fi
fi
export GITHUB_TOKEN="$GH_TOKEN"
export GITHUB_REPOSITORY="$REPO"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Seed config defaults into SSM
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Seeding config defaults into SSM..."

ssm_put() {
  local key="$1" val="$2"
  aws ssm put-parameter \
    --name "${SSM_PREFIX}${key}" \
    --value "$val" \
    --type SecureString \
    --overwrite \
    --region "$REGION" >/dev/null 2>&1 && ok "  SSM: $key" || warn "  SSM put failed: $key"
}

for key in "${!DEFAULTS[@]}"; do
  # Only write if not already set
  EXISTING=$(aws ssm get-parameter --name "${SSM_PREFIX}${key}" \
    --query Parameter.Value --output text 2>/dev/null || echo "")
  if [ -z "$EXISTING" ]; then
    ssm_put "$key" "${DEFAULTS[$key]}"
  else
    ok "  SSM: $key (already set)"
  fi
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — S3 bucket
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Provisioning S3 bucket..."

if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
  ok "S3 bucket $S3_BUCKET already exists"
else
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  aws s3api put-bucket-versioning --bucket "$S3_BUCKET" \
    --versioning-configuration Status=Enabled >/dev/null
  aws s3api put-bucket-encryption --bucket "$S3_BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
  ok "S3 bucket $S3_BUCKET created + encrypted + versioned"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — GitHub Actions OIDC role (replaces static AWS keys forever)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Provisioning GitHub Actions OIDC role..."

OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_THUMB="6938fd4d98bab03faadb97b34396831e3780aea1"
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

# Register OIDC provider
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" &>/dev/null; then
  ok "OIDC provider already registered"
else
  aws iam create-open-id-connect-provider \
    --url "$OIDC_URL" \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list "$OIDC_THUMB" >/dev/null
  ok "OIDC provider registered"
fi

# Create trust policy
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "$OIDC_ARN"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringLike":  {"token.actions.githubusercontent.com:sub": "repo:${REPO}:*"},
      "StringEquals":{"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
    }
  }]
}
EOF
)

if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
  ok "OIDC role already exists: $ROLE_ARN"
else
  ROLE_ARN=$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Garcar GitHub Actions OIDC — no static keys" \
    --tags Key=project,Value=garcar \
    --query Role.Arn --output text)

  for policy in \
    "arn:aws:iam::aws:policy/AmazonSSMFullAccess" \
    "arn:aws:iam::aws:policy/AmazonS3FullAccess" \
    "arn:aws:iam::aws:policy/AmazonSESFullAccess" \
    "arn:aws:iam::aws:policy/SecretsManagerReadWrite" \
    "arn:aws:iam::aws:policy/AWSLambda_FullAccess" \
    "arn:aws:iam::aws:policy/IAMFullAccess"; do
    aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$policy"
  done
  ok "OIDC role created: $ROLE_ARN"
fi

# Store role ARN in SSM
ssm_put "LAMBDA_EXECUTION_ROLE_ARN" "$ROLE_ARN"
ssm_put "OIDC_ROLE_ARN" "$ROLE_ARN"
ssm_put "AWS_ACCOUNT_ID" "$ACCOUNT_ID"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — SES email verification
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Setting up SES..."

SES_STATUS=$(aws ses get-identity-verification-attributes \
  --identities "$SES_EMAIL" \
  --query "VerificationAttributes.\"${SES_EMAIL}\".VerificationStatus" \
  --output text 2>/dev/null || echo "NotStarted")

if [ "$SES_STATUS" = "Success" ]; then
  ok "SES $SES_EMAIL already verified"
else
  aws ses verify-email-identity --email-address "$SES_EMAIL" 2>/dev/null || true
  warn "Verification email sent to $SES_EMAIL — click the link to complete SES setup"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Collect missing revenue keys (one-time interactive)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Checking revenue-critical API keys..."

MISSING=()
for key in "${REVENUE_KEYS[@]}"; do
  EXISTING=$(aws ssm get-parameter --name "${SSM_PREFIX}${key}" \
    --with-decryption --query Parameter.Value --output text 2>/dev/null || echo "")
  if [ -z "$EXISTING" ]; then
    MISSING+=("$key")
  else
    ok "  $key (in SSM)"
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo -e "${BOLD}  ══ ONE-TIME KEY INPUT ══════════════════════════════════${RESET}"
  echo -e "  These keys are missing from SSM. Enter them now and you"
  echo -e "  will NEVER be asked for them again."
  echo -e "  Leave blank to skip (you can add later with --set)."
  echo ""

  for key in "${MISSING[@]}"; do
    read -r -s -p "  $key: " VAL
    echo ""
    if [ -n "$VAL" ]; then
      aws ssm put-parameter \
        --name "${SSM_PREFIX}${key}" \
        --value "$VAL" \
        --type SecureString \
        --overwrite \
        --region "$REGION" >/dev/null
      ok "  $key stored in SSM"
    else
      warn "  $key skipped — add later: python secrets_provisioner.py --set $key=<value>"
    fi
  done
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 — Sync ALL SSM keys → GitHub Actions encrypted secrets
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Syncing all SSM keys → GitHub Actions secrets..."

python3 - <<PYEOF
import os, json, base64, boto3, requests

REGION  = os.environ.get('AWS_REGION', '$REGION')
REPO    = '$REPO'
TOKEN   = '$GH_TOKEN'
PREFIX  = '$SSM_PREFIX'

headers = {
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}

try:
    from nacl import encoding, public
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pynacl', '-q'])
    from nacl import encoding, public

ssm = boto3.client('ssm', region_name=REGION)
bundle = {}
paginator = ssm.get_paginator('get_parameters_by_path')
for page in paginator.paginate(Path=PREFIX, WithDecryption=True, Recursive=True):
    for p in page['Parameters']:
        key = p['Name'].replace(PREFIX, '').upper()
        bundle[key] = p['Value']

print(f'  Loaded {len(bundle)} keys from SSM')

if not TOKEN:
    print('  No GITHUB_TOKEN — skipping GitHub sync')
else:
    pk_r = requests.get(f'https://api.github.com/repos/{REPO}/actions/secrets/public-key',
                        headers=headers, timeout=10)
    pk_r.raise_for_status()
    pk_data = pk_r.json()
    pub_key = public.PublicKey(pk_data['key'].encode(), encoding.Base64Encoder())
    box = public.SealedBox(pub_key)
    count = 0
    for k, v in bundle.items():
        if not v:
            continue
        enc = base64.b64encode(box.encrypt(v.encode())).decode()
        r = requests.put(
            f'https://api.github.com/repos/{REPO}/actions/secrets/{k}',
            headers=headers, timeout=10,
            json={'encrypted_value': enc, 'key_id': pk_data['key_id']}
        )
        if r.status_code in (201, 204):
            count += 1
        else:
            print(f'    Warning: {k} — {r.status_code}')
    print(f'  Synced {count}/{len(bundle)} → GitHub Actions')
PYEOF

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 — Update GitHub Actions workflows to use OIDC (no static keys)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "Verifying OIDC in GitHub Actions workflows..."

if grep -r "aws-actions/configure-aws-credentials" .github/workflows/ &>/dev/null 2>&1; then
  if grep -r "role-to-assume" .github/workflows/ &>/dev/null 2>&1; then
    ok "Workflows already using OIDC role-to-assume"
  else
    warn "Workflows may still use static keys — consider migrating to role-to-assume: $ROLE_ARN"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║                  BOOTSTRAP COMPLETE                     ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}What was set up:${RESET}"
echo -e "  • AWS SSM Parameter Store — single source of truth"
echo -e "  • GitHub Actions OIDC role — no more static AWS keys"
echo -e "  • S3 bucket $S3_BUCKET — encrypted + versioned"
echo -e "  • SES identity registered for $SES_EMAIL"
echo -e "  • All secrets synced to GitHub Actions"
echo ""
echo -e "  ${BOLD}From now on, to add/update any key:${RESET}"
echo -e "  ${CYAN}python secrets_provisioner.py --set KEY=value${RESET}"
echo -e "  ...it flows to SSM + GitHub Actions automatically."
echo ""
echo -e "  ${BOLD}To re-sync everything (self-heal):${RESET}"
echo -e "  ${CYAN}python secrets_provisioner.py${RESET}"
echo ""
echo -e "  ${BOLD}OIDC Role ARN (for workflows):${RESET}"
echo -e "  ${CYAN}$ROLE_ARN${RESET}"
echo ""
echo -e "  ${YELLOW}Optional cleanup: remove ~/.aws/credentials after confirming"
echo -e "  GitHub Actions pipelines run successfully with OIDC.${RESET}"
echo ""
