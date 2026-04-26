#!/usr/bin/env bash
# =============================================================================
# GARCAR CLOUDSHELL MASTER — Run ONCE inside AWS CloudShell
# Opens at: https://console.aws.amazon.com/cloudshell
#
# What this does in one shot:
#   1.  Installs all deps (boto3, pynacl, requests) inside CloudShell
#   2.  Detects your AWS account ID automatically (no keys needed — CloudShell
#       inherits your console session)
#   3.  Creates the OIDC role so GitHub Actions NEVER needs static AWS keys
#   4.  Provisions S3 bucket + SES sender
#   5.  Seeds all config defaults into SSM Parameter Store
#   6.  Prompts ONCE for API keys (Stripe, OpenAI, etc.) → stored in SSM
#   7.  Syncs ALL SSM secrets → GitHub Actions encrypted secrets
#   8.  Creates an API Gateway endpoint that your PHONE hits to trigger
#       any agent remotely — no code runs on your phone, ever
#   9.  Sends you the phone trigger URL + sets it as GitHub secret
#  10.  Stores your Perplexity API key so agents use it for AI reasoning
#       (Perplexity replaces local LLM — zero compute on your device)
#
# Run:
#   curl -fsSL https://raw.githubusercontent.com/Garrettc123/garcar-autonomous-wealth-system/main/cloudshell_master.sh | bash
# OR paste this file into AWS CloudShell directly.
# =============================================================================

set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────────────
BOLD="\033[1m"; GREEN="\033[1;32m"; YELLOW="\033[1;33m"
CYAN="\033[1;36m"; RED="\033[1;31m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}  ✓ $*${RESET}"; }
info() { echo -e "${CYAN}  → $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${RESET}"; }
die()  { echo -e "${RED}  ✗ $*${RESET}"; exit 1; }

# ── Config ────────────────────────────────────────────────────────────────────────
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
SSM="/garcar/"
REPO="Garrettc123/garcar-autonomous-wealth-system"
ROLE="garcar-github-actions-role"
S3="garcar-revenue-data"
SES_EMAIL="noreply@garcar.io"
API_NAME="garcar-phone-trigger"
LAMBDA_AGENT="garcar-orchestrator"
GH_API="https://api.github.com"

# Revenue keys to collect once
REVENUE_KEYS=(
  GITHUB_TOKEN
  STRIPE_SECRET_KEY
  STRIPE_PUBLISHABLE_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_PRO
  STRIPE_PRICE_STARTER
  OPENAI_API_KEY
  PERPLEXITY_API_KEY
  APOLLO_API_KEY
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_PHONE_NUMBER
  SENDGRID_API_KEY
  LINEAR_API_KEY
  LINEAR_TEAM_ID
  ZAPIER_WEBHOOK_URL
)

# Non-sensitive defaults
declare -A DEFAULTS=(
  [AWS_REGION]="$REGION"
  [S3_BUCKET]="$S3"
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
# BANNER
# ─────────────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}"
cat << 'BANNER'
╔══════════════════════════════════════════════════════════╗
║   GARCAR CLOUDSHELL MASTER — ZERO-KEY PHONE LINK   ║
║   AWS CloudShell → OIDC → SSM → GitHub → Lambda   ║
║   Your phone triggers agents. Zero code on device.  ║
╚══════════════════════════════════════════════════════════╝
BANNER
echo -e "${RESET}"

# ── STEP 1: Verify CloudShell AWS identity ────────────────────────────────────────
info "Checking AWS CloudShell identity..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
  || die "Not in CloudShell or no AWS session. Open https://console.aws.amazon.com/cloudshell"
ok "AWS Account: $ACCOUNT_ID  Region: $REGION"

# ── STEP 2: Install deps ──────────────────────────────────────────────────────────────────
info "Installing Python deps..."
pip install --quiet --upgrade boto3 requests pynacl 2>/dev/null
ok "Deps ready"

# ── STEP 3: Seed SSM defaults ──────────────────────────────────────────────────────────────
info "Seeding SSM config defaults..."
ssm_put() {
  aws ssm put-parameter --name "${SSM}$1" --value "$2" \
    --type SecureString --overwrite --region "$REGION" >/dev/null 2>&1 && ok "  SSM $1" || warn "  SSM skip $1"
}
ssm_get() {
  aws ssm get-parameter --name "${SSM}$1" --with-decryption \
    --query Parameter.Value --output text 2>/dev/null || echo ""
}
for k in "${!DEFAULTS[@]}"; do
  [ -z "$(ssm_get $k)" ] && ssm_put "$k" "${DEFAULTS[$k]}" || ok "  SSM $k (exists)"
done

# ── STEP 4: S3 Bucket ───────────────────────────────────────────────────────────────────────────
info "Provisioning S3 bucket..."
if aws s3api head-bucket --bucket "$S3" 2>/dev/null; then
  ok "S3 $S3 exists"
else
  [ "$REGION" = "us-east-1" ] \
    && aws s3api create-bucket --bucket "$S3" --region "$REGION" >/dev/null \
    || aws s3api create-bucket --bucket "$S3" --region "$REGION" \
         --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  aws s3api put-bucket-versioning --bucket "$S3" \
    --versioning-configuration Status=Enabled >/dev/null
  aws s3api put-bucket-encryption --bucket "$S3" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
  ok "S3 $S3 created"
fi

# ── STEP 5: OIDC Role ───────────────────────────────────────────────────────────────────────────
info "Creating OIDC role for GitHub Actions..."
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" &>/dev/null; then
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
  ok "OIDC provider registered"
else
  ok "OIDC provider exists"
fi

TRUST=$(cat <<TRUST
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Federated":"$OIDC_ARN"},"Action":"sts:AssumeRoleWithWebIdentity","Condition":{"StringLike":{"token.actions.githubusercontent.com:sub":"repo:${REPO}:*"},"StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com"}}}]}
TRUST
)

if aws iam get-role --role-name "$ROLE" &>/dev/null; then
  ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)
  ok "OIDC role exists: $ROLE_ARN"
else
  ROLE_ARN=$(aws iam create-role --role-name "$ROLE" \
    --assume-role-policy-document "$TRUST" \
    --description "Garcar OIDC — no static keys" \
    --tags Key=project,Value=garcar \
    --query Role.Arn --output text)
  for p in AmazonSSMFullAccess AmazonS3FullAccess AmazonSESFullAccess \
            SecretsManagerReadWrite AWSLambda_FullAccess IAMFullAccess \
            AmazonAPIGatewayAdministrator AWSStepFunctionsFullAccess; do
    aws iam attach-role-policy --role-name "$ROLE" \
      --policy-arn "arn:aws:iam::aws:policy/$p" >/dev/null
  done
  ok "OIDC role created: $ROLE_ARN"
fi

ssm_put "OIDC_ROLE_ARN" "$ROLE_ARN"
ssm_put "LAMBDA_EXECUTION_ROLE_ARN" "$ROLE_ARN"
ssm_put "AWS_ACCOUNT_ID" "$ACCOUNT_ID"

# ── STEP 6: SES ───────────────────────────────────────────────────────────────────────────────
info "SES sender verification..."
SES_STATUS=$(aws ses get-identity-verification-attributes --identities "$SES_EMAIL" \
  --query "VerificationAttributes.\"${SES_EMAIL}\".VerificationStatus" \
  --output text 2>/dev/null || echo "")
[ "$SES_STATUS" = "Success" ] \
  && ok "SES verified" \
  || { aws ses verify-email-identity --email-address "$SES_EMAIL" 2>/dev/null || true
       warn "Check $SES_EMAIL inbox and click verify link"; }

# ── STEP 7: Collect API keys one-time ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════ ONE-TIME KEY INPUT ═══════════════${RESET}"
echo -e "  Enter each key. Leave blank to skip (add later with:"
echo -e "  ${CYAN}python secrets_provisioner.py --set KEY=value${RESET} )"
echo ""

for KEY in "${REVENUE_KEYS[@]}"; do
  EXISTING=$(ssm_get "$KEY")
  if [ -n "$EXISTING" ]; then
    ok "  $KEY already in SSM"
  else
    read -r -s -p "  $KEY: " VAL; echo ""
    if [ -n "$VAL" ]; then
      ssm_put "$KEY" "$VAL"
      ok "  $KEY stored"
    else
      warn "  $KEY skipped"
    fi
  fi
done

# Extract GitHub token for API calls
GH_TOKEN=$(ssm_get "GITHUB_TOKEN")
[ -z "$GH_TOKEN" ] && die "GITHUB_TOKEN is required — re-run and enter it."
export GITHUB_TOKEN="$GH_TOKEN"

# ── STEP 8: Phone trigger Lambda (inline — no zip needed) ─────────────────────────
info "Creating phone-trigger Lambda..."

PHONE_LAMBDA_CODE=$(cat <<'PYCODE'
import json, os, boto3, urllib.request, urllib.parse

def handler(event, context):
    body = json.loads(event.get('body') or '{}')
    action   = body.get('action', 'run_all')
    token    = os.environ['TRIGGER_TOKEN']
    gh_token = os.environ['GITHUB_TOKEN']
    repo     = os.environ['GITHUB_REPOSITORY']

    # Verify secret token so only your phone can trigger
    if body.get('token') != token:
        return {'statusCode': 401, 'body': json.dumps({'error': 'Unauthorized'})}

    # Map action -> GitHub Actions workflow
    WORKFLOW_MAP = {
        'run_all':        'master-revenue-trigger.yml',
        'leads':          'customer-acquisition-loop.yml',
        'deploy':         'deploy.yml',
        'provision':      'garcar-zero-key.yml',
        'orchestrate':    'master-orchestrator.yml',
    }
    workflow = WORKFLOW_MAP.get(action, 'master-revenue-trigger.yml')

    # Trigger via GitHub API
    url = f'https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches'
    payload = json.dumps({'ref': 'main', 'inputs': {}}).encode()
    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Authorization', f'token {gh_token}')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    try:
        urllib.request.urlopen(req, timeout=10)
        return {'statusCode': 200, 'body': json.dumps({'triggered': workflow, 'action': action})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
PYCODE
)

# Create Lambda zip in memory via Python
python3 - <<PYBUILD
import zipfile, io, subprocess, json, boto3, os, base64

code = '''$PHONE_LAMBDA_CODE'''
region = '$REGION'
role_arn = '$ROLE_ARN'
github_token = '$(ssm_get GITHUB_TOKEN)'
trigger_token = '$(openssl rand -hex 32)'
repo = '$REPO'

# Zip code
buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as zf:
    zf.writestr('index.py', code)
buf.seek(0)
zipped = buf.read()

client = boto3.client('lambda', region_name=region)
env = {
    'TRIGGER_TOKEN':     trigger_token,
    'GITHUB_TOKEN':      github_token,
    'GITHUB_REPOSITORY': repo,
}

try:
    client.update_function_code(FunctionName='garcar-phone-trigger', ZipFile=zipped)
    client.update_function_configuration(
        FunctionName='garcar-phone-trigger',
        Environment={'Variables': env}
    )
    print('  Updated existing phone-trigger Lambda')
except client.exceptions.ResourceNotFoundException:
    client.create_function(
        FunctionName='garcar-phone-trigger',
        Runtime='python3.11',
        Role=role_arn,
        Handler='index.handler',
        Code={'ZipFile': zipped},
        Timeout=30,
        MemorySize=256,
        Environment={'Variables': env},
        Description='Garcar phone trigger — routes phone commands to GitHub Actions'
    )
    print('  Created phone-trigger Lambda')

# Store trigger token in SSM
ssm = boto3.client('ssm', region_name=region)
ssm.put_parameter(Name='/garcar/PHONE_TRIGGER_TOKEN', Value=trigger_token,
                  Type='SecureString', Overwrite=True)
print(f'  Trigger token stored in SSM')

# Write token to temp file for next step
with open('/tmp/trigger_token.txt', 'w') as f:
    f.write(trigger_token)
PYBUILD

TRIGGER_TOKEN=$(cat /tmp/trigger_token.txt 2>/dev/null || echo "")
[ -z "$TRIGGER_TOKEN" ] && warn "Could not read trigger token" || ok "Phone trigger Lambda deployed"

# ── STEP 9: API Gateway → phone URL ────────────────────────────────────────────────────
info "Creating API Gateway phone endpoint..."

PHONE_URL=$(python3 - <<PYAPI
import boto3, json

region = '$REGION'
account = '$ACCOUNT_ID'

apigw = boto3.client('apigatewayv2', region_name=region)

# Check if already exists
apis = apigw.get_apis()['Items']
existing = next((a for a in apis if a['Name'] == 'garcar-phone-trigger'), None)

if existing:
    api_id = existing['ApiId']
    print(f'https://{api_id}.execute-api.{region}.amazonaws.com/trigger')
else:
    resp = apigw.create_api(
        Name='garcar-phone-trigger',
        ProtocolType='HTTP',
        Target=f'arn:aws:lambda:{region}:{account}:function:garcar-phone-trigger',
        Description='Garcar phone-to-cloud trigger endpoint'
    )
    api_id  = resp['ApiId']
    api_url = resp['ApiEndpoint']

    # Grant API GW permission to invoke Lambda
    import boto3 as b
    lam = b.client('lambda', region_name=region)
    try:
        lam.add_permission(
            FunctionName='garcar-phone-trigger',
            StatementId='apigateway-invoke',
            Action='lambda:InvokeFunction',
            Principal='apigateway.amazonaws.com',
            SourceArn=f'arn:aws:execute-api:{region}:{account}:{api_id}/*/*'
        )
    except lam.exceptions.ResourceConflictException:
        pass

    print(f'{api_url}/trigger')
PYAPI
)

if [ -n "$PHONE_URL" ]; then
  ok "Phone URL: $PHONE_URL"
  ssm_put "PHONE_TRIGGER_URL" "$PHONE_URL"
else
  warn "API Gateway setup incomplete — check Lambda permissions"
  PHONE_URL="(see AWS API Gateway console)"
fi

# ── STEP 10: Sync ALL SSM → GitHub Actions ─────────────────────────────────────────────
info "Syncing all SSM keys → GitHub Actions..."

python3 - <<PYSYNC
import os, json, base64, boto3, requests
from nacl import encoding, public

REGION = '$REGION'
REPO   = '$REPO'
TOKEN  = '$GH_TOKEN'
PREFIX = '$SSM'

ssm = boto3.client('ssm', region_name=REGION)
bundle = {}
paginator = ssm.get_paginator('get_parameters_by_path')
for page in paginator.paginate(Path=PREFIX, WithDecryption=True, Recursive=True):
    for p in page['Parameters']:
        k = p['Name'].replace(PREFIX, '').upper()
        bundle[k] = p['Value']
print(f'  Loaded {len(bundle)} keys from SSM')

hdrs = {
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}
pk = requests.get(f'https://api.github.com/repos/{REPO}/actions/secrets/public-key', headers=hdrs, timeout=10).json()
pub = public.PublicKey(pk['key'].encode(), encoding.Base64Encoder())
box = public.SealedBox(pub)
count = 0
for k, v in bundle.items():
    if not v: continue
    enc = base64.b64encode(box.encrypt(v.encode())).decode()
    r = requests.put(f'https://api.github.com/repos/{REPO}/actions/secrets/{k}',
                     headers=hdrs, timeout=10,
                     json={'encrypted_value': enc, 'key_id': pk['key_id']})
    count += 1 if r.status_code in (201, 204) else 0
print(f'  Synced {count}/{len(bundle)} → GitHub Actions')
PYSYNC

# ── FINAL: Print phone setup card ────────────────────────────────────────────────────────
rm -f /tmp/trigger_token.txt

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║           SETUP COMPLETE — PHONE CARD                  ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}Your phone trigger URL:${RESET}"
echo -e "  ${CYAN}$PHONE_URL${RESET}"
echo ""
echo -e "  ${BOLD}Your secret token:${RESET} (stored in SSM /garcar/PHONE_TRIGGER_TOKEN)"
echo -e "  ${CYAN}$TRIGGER_TOKEN${RESET}"
echo ""
echo -e "  ${BOLD}From your phone (Shortcuts / HTTP client / anything):${RESET}"
echo ""
echo -e "  ${YELLOW}Trigger ALL agents:${RESET}"
echo    "  curl -X POST \\$PHONE_URL\\"
echo    "    -H 'Content-Type: application/json' \\"
echo    "    -d '{\"token\":\"$TRIGGER_TOKEN\",\"action\":\"run_all\"}'"
echo ""
echo -e "  ${YELLOW}Other actions: leads | deploy | provision | orchestrate${RESET}"
echo ""
echo -e "  ${BOLD}Perplexity AI key stored in SSM as PERPLEXITY_API_KEY${RESET}"
echo -e "  Agents call Perplexity for reasoning — zero compute on your phone."
echo ""
echo -e "  ${BOLD}Every 6 hours:${RESET} garcar-zero-key.yml self-heals all secrets."
echo -e "  ${BOLD}Every push to main:${RESET} full provisioner re-runs automatically."
echo ""
