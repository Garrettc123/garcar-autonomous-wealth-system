#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# GARCAR TERMUX AUTO KEY DISCOVERY + INJECTION AGENT
# Crawls every known key location on device → injects to SSM
# Run: bash termux_key_discovery.sh
# ============================================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[GARCAR]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()  { echo -e "${RED}[ERR]${NC}   $1"; }
info() { echo -e "${CYAN}[INFO]${NC}  $1"; }

DISCOVERED_ENV="/tmp/garcar_discovered.env"
INJECTED=0
FOUND=0

> "$DISCOVERED_ENV"

echo ""
echo "============================================================"
echo "  GARCAR AUTO KEY DISCOVERY — $(date)"
echo "============================================================"

# ── KEY PATTERNS TO HUNT ─────────────────────────────────────
declare -A KEY_PATTERNS=(
  [STRIPE_SECRET_KEY]='sk_live_[A-Za-z0-9]+|sk_test_[A-Za-z0-9]+'
  [STRIPE_PUBLISHABLE_KEY]='pk_live_[A-Za-z0-9]+|pk_test_[A-Za-z0-9]+'
  [STRIPE_WEBHOOK_SECRET]='whsec_[A-Za-z0-9]+'
  [OPENAI_API_KEY]='sk-[A-Za-z0-9\-_]{40,}'
  [APOLLO_API_KEY]='[A-Za-z0-9_\-]{30,}'
  [TWILIO_AUTH_TOKEN]='[a-f0-9]{32}'
  [LINEAR_API_KEY]='lin_api_[A-Za-z0-9]+'
  [ANTHROPIC_API_KEY]='sk-ant-[A-Za-z0-9\-_]+'
  [AWS_ACCESS_KEY_ID]='AKIA[A-Z0-9]{16}'
  [AWS_SECRET_ACCESS_KEY]='[A-Za-z0-9/+=]{40}'
  [GITHUB_TOKEN]='gh[ps]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]+'
  [VERCEL_TOKEN]='[A-Za-z0-9]{24}'
)

# ── SEARCH LOCATIONS ─────────────────────────────────────────
SEARCH_PATHS=(
  "$HOME/.env"
  "$HOME/.env.local"
  "$HOME/.env.production"
  "$HOME/.env.garcar"
  "$HOME/.bashrc"
  "$HOME/.bash_profile"
  "$HOME/.zshrc"
  "$HOME/.profile"
  "$HOME/.config/garcar/.env"
  "$HOME/.aws/credentials"
  "$HOME/.aws/config"
  "$HOME/garcar-autonomous-wealth-system/.env"
  "$HOME/garcar-autonomous-wealth-system/.env.local"
  "$HOME/garcar-autonomous-wealth-system/.env.production"
  "$HOME/api-key-automaton/.env"
  "$HOME/nwu-protocol/.env"
  "$HOME/systems-master-hub/.env"
  "/sdcard/.garcar.env"
  "/sdcard/garcar/.env"
  "/sdcard/Download/.garcar.env"
  "/data/data/com.termux/files/home/.env"
)

# ── DYNAMIC REPO SCAN ────────────────────────────────────────
# Also scan any repo cloned under $HOME
for repo_env in "$HOME"/*/.env "$HOME"/*/.env.local "$HOME"/*/.env.production 2>/dev/null; do
  [[ -f "$repo_env" ]] && SEARCH_PATHS+=("$repo_env")
done

# ── EXTRACT FUNCTION ─────────────────────────────────────────
extract_from_file() {
  local file="$1"
  [[ ! -f "$file" ]] && return
  info "Scanning: $file"

  # Pattern 1: KEY=value or export KEY=value
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*#  ]] && continue
    [[ "$line" =~ ^[[:space:]]*$  ]] && continue
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Z_][A-Z0-9_]+)[[:space:]]*=[[:space:]]*[\'\"']?([^\'\"'[:space:]]+)[\'\"']? ]]; then
      local k="${BASH_REMATCH[2]}"
      local v="${BASH_REMATCH[3]}"
      [[ -z "$v" || "$v" == "your_*" || "$v" == "REPLACE*" || "$v" == "xxx*" ]] && continue
      echo "${k}=${v}" >> "$DISCOVERED_ENV"
      ((FOUND++)) || true
      log "  Found: ${k}=****"
    fi
  done < "$file"

  # Pattern 2: AWS credentials file [default] block
  if [[ "$file" == *"credentials"* ]]; then
    local ak secret
    ak=$(grep -oP '(?<=aws_access_key_id\s=\s)AKIA[A-Z0-9]{16}' "$file" 2>/dev/null || true)
    secret=$(grep -oP '(?<=aws_secret_access_key\s=\s)[A-Za-z0-9/+=]{40}' "$file" 2>/dev/null || true)
    [[ -n "$ak" ]] && { echo "AWS_ACCESS_KEY_ID=${ak}" >> "$DISCOVERED_ENV"; log "  Found: AWS_ACCESS_KEY_ID"; ((FOUND++)) || true; }
    [[ -n "$secret" ]] && { echo "AWS_SECRET_ACCESS_KEY=${secret}" >> "$DISCOVERED_ENV"; log "  Found: AWS_SECRET_ACCESS_KEY"; ((FOUND++)) || true; }
  fi
}

# ── RUN SCANS ────────────────────────────────────────────────
log "Scanning ${#SEARCH_PATHS[@]} known locations..."
for path in "${SEARCH_PATHS[@]}"; do
  extract_from_file "$path"
done

# ── DEEP SCAN: find all .env files under $HOME ───────────────
log "Deep scanning all .env files under \$HOME..."
while IFS= read -r envfile; do
  extract_from_file "$envfile"
done < <(find "$HOME" -maxdepth 6 -name '*.env' -o -name '.env' -o -name '.env.*' 2>/dev/null | grep -v '.git' | grep -v 'node_modules')

echo ""
log "Discovery complete. Found ${FOUND} raw key entries."

[[ $FOUND -eq 0 ]] && { warn "No keys found on device. Nothing to inject."; exit 0; }

# ── DEDUP + CLEAN ────────────────────────────────────────────
sort -u -t= -k1,1 "$DISCOVERED_ENV" -o "$DISCOVERED_ENV"
log "Deduplicated to $(wc -l < "$DISCOVERED_ENV") unique keys."

# ── INJECT TO SSM ────────────────────────────────────────────
echo ""
log "Injecting into AWS SSM Parameter Store (/garcar/*)"

if ! command -v aws &>/dev/null; then
  warn "AWS CLI not found. Installing..."
  pip install awscli --quiet
fi

if ! command -v python3 &>/dev/null; then
  warn "Python3 not found. Installing..."
  pkg install python -y
fi

# Load the discovered keys into current shell
set -a
# shellcheck source=/dev/null
source "$DISCOVERED_ENV"
set +a

# Inject each key to SSM
while IFS='=' read -r key value; do
  [[ -z "$key" || -z "$value" ]] && continue
  [[ "$key" =~ ^# ]] && continue

  aws ssm put-parameter \
    --name "/garcar/${key}" \
    --value "${value}" \
    --type SecureString \
    --overwrite \
    --region "${AWS_REGION:-us-east-1}" \
    --no-cli-pager 2>/dev/null && {
      log "  Injected: /garcar/${key}"
      ((INJECTED++)) || true
    } || {
      warn "  SSM failed for ${key} — storing in local .env.garcar instead"
      echo "${key}=${value}" >> "$HOME/.env.garcar"
    }
done < "$DISCOVERED_ENV"

# ── TRIGGER GITHUB SYNC ──────────────────────────────────────
echo ""
log "Triggering GitHub Actions secrets sync..."

if command -v python3 &>/dev/null; then
  REPO_DIR="$(find $HOME -maxdepth 3 -name 'secrets_provisioner.py' -exec dirname {} \; 2>/dev/null | head -1)"
  if [[ -n "$REPO_DIR" ]]; then
    log "Running secrets_provisioner.py from $REPO_DIR"
    cd "$REPO_DIR"
    pip install boto3 requests pynacl --quiet 2>/dev/null
    python3 secrets_provisioner.py
  else
    warn "secrets_provisioner.py not found — pull the repo first:"
    warn "  git clone https://github.com/Garrettc123/garcar-autonomous-wealth-system"
  fi
fi

# ── FINAL REPORT ────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  GARCAR AUTO-INJECTION COMPLETE"
echo "  Found:    ${FOUND} keys"
echo "  Injected: ${INJECTED} keys → SSM /garcar/*"
echo "  $(date)"
echo "============================================================"
echo ""
log "From this point forward, all Garcar systems pull keys from SSM automatically."
log "Zero manual key entry required."
rm -f "$DISCOVERED_ENV"
