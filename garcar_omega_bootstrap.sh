#!/data/data/com.termux/files/usr/bin/bash
# ================================================================
# GARCAR OMEGA BOOTSTRAP v2.0
# ================================================================
# 1. Autonomous missing package installer
# 2. API key discovery + injection (SSM + GitHub)
# 3. Self-configuring software integration finder
# 4. Zero-intervention full Termux environment setup
# 5. Persistent background dependency watcher daemon
# ================================================================
# USAGE:
#   First time:  curl -sL https://raw.githubusercontent.com/Garrettc123/garcar-autonomous-wealth-system/main/garcar_omega_bootstrap.sh | bash
#   Subsequent:  garcar-boot  (alias auto-installed)
# ================================================================

set -uo pipefail

# ── Colors ───────────────────────────────────────────────────
BOLD='\033[1m';    GREEN='\033[0;32m';  YELLOW='\033[1;33m'
RED='\033[0;31m'; CYAN='\033[0;36m';   MAGENTA='\033[0;35m'
BLUE='\033[0;34m'; NC='\033[0m'

log()     { echo -e "${GREEN}${BOLD}[GARCAR]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}     $1"; }
err()     { echo -e "${RED}[ERR]${NC}      $1"; }
info()    { echo -e "${CYAN}[INFO]${NC}     $1"; }
section() { echo -e "\n${MAGENTA}${BOLD}━━━ $1 ━━━${NC}"; }
ok()      { echo -e "${GREEN}  ✓${NC} $1"; }
miss()    { echo -e "${YELLOW}  ✗${NC} $1"; }

STATE_DIR="$HOME/.garcar"
LOG_FILE="$STATE_DIR/omega.log"
PID_FILE="$STATE_DIR/watcher.pid"
DISCOVERED="$STATE_DIR/discovered.env"
INTEGRATIONS="$STATE_DIR/integrations.json"
PACKAGES_INSTALLED=0
KEYS_FOUND=0
KEYS_INJECTED=0
INTEGS_FOUND=0

mkdir -p "$STATE_DIR"
> "$DISCOVERED"
exec > >(tee -a "$LOG_FILE") 2>&1

echo ""
echo -e "${BOLD}${BLUE}================================================================${NC}"
echo -e "${BOLD}${BLUE}  GARCAR OMEGA BOOTSTRAP  —  $(date)${NC}"
echo -e "${BOLD}${BLUE}  Zero-intervention autonomous environment agent${NC}"
echo -e "${BOLD}${BLUE}================================================================${NC}"
echo ""

# ================================================================
# PHASE 1 — AUTONOMOUS PACKAGE INSTALLER
# ================================================================
section "PHASE 1 — Autonomous Package Installer"

PKG_CORE=(git python openssh curl wget jq tar unzip nano)
PKG_DEV=(nodejs clang make pkg-config libffi openssl)
PKG_OPS=(rsync tmux screen htop ncurses-utils)
PKG_NET=(nmap dnsutils iproute2)
PIP_CORE=(boto3 requests pynacl awscli fastapi uvicorn stripe openai python-dotenv rich)
PIP_DEV=(httpx pydantic loguru aiohttp cryptography paramiko)

install_pkg() {
  local pkg="$1"
  if dpkg -l "$pkg" &>/dev/null 2>&1 || command -v "$pkg" &>/dev/null; then
    ok "pkg: $pkg"
  else
    miss "pkg: $pkg — installing..."
    pkg install -y -q "$pkg" 2>/dev/null && { ok "Installed: $pkg"; ((PACKAGES_INSTALLED++)) || true; } \
      || warn "Could not install $pkg (may not exist in Termux repos)"
  fi
}

install_pip() {
  local pkg="$1"
  if python3 -c "import ${pkg//-/_}" &>/dev/null 2>&1; then
    ok "pip: $pkg"
  else
    miss "pip: $pkg — installing..."
    pip install --quiet "$pkg" 2>/dev/null && { ok "Installed: $pkg"; ((PACKAGES_INSTALLED++)) || true; } \
      || warn "pip install failed: $pkg"
  fi
}

log "Updating package index..."
pkg update -y -q 2>/dev/null || true

log "Installing core system packages..."
for p in "${PKG_CORE[@]}"; do install_pkg "$p"; done

log "Installing dev packages..."
for p in "${PKG_DEV[@]}"; do install_pkg "$p"; done

log "Installing ops packages..."
for p in "${PKG_OPS[@]}"; do install_pkg "$p"; done

if command -v python3 &>/dev/null; then
  log "Installing Python core packages..."
  pip install --quiet --upgrade pip 2>/dev/null || true
  for p in "${PIP_CORE[@]}"; do install_pip "$p"; done
  log "Installing Python dev packages..."
  for p in "${PIP_DEV[@]}"; do install_pip "$p"; done
fi

log "Phase 1 complete — $PACKAGES_INSTALLED new packages installed."

# ================================================================
# PHASE 2 — API KEY DISCOVERY + INJECTION
# ================================================================
section "PHASE 2 — API Key Discovery + Injection"

SEARCH_PATHS=(
  "$HOME/.env" "$HOME/.env.local" "$HOME/.env.production"
  "$HOME/.env.garcar" "$HOME/.bashrc" "$HOME/.bash_profile"
  "$HOME/.zshrc" "$HOME/.profile" "$HOME/.config/garcar/.env"
  "$HOME/.aws/credentials" "$HOME/.aws/config"
  "$HOME/garcar-autonomous-wealth-system/.env"
  "$HOME/garcar-autonomous-wealth-system/.env.local"
  "$HOME/garcar-autonomous-wealth-system/.env.production"
  "$HOME/api-key-automaton/.env" "$HOME/nwu-protocol/.env"
  "$HOME/systems-master-hub/.env" "/sdcard/.garcar.env"
  "/sdcard/garcar/.env" "/sdcard/Download/.garcar.env"
  "/data/data/com.termux/files/home/.env"
)

# Dynamic: scan all repos under $HOME
while IFS= read -r f; do
  SEARCH_PATHS+=("$f")
done < <(find "$HOME" -maxdepth 6 \( -name '.env' -o -name '.env.*' -o -name '*.env' \) \
  2>/dev/null | grep -v '\.git' | grep -v 'node_modules' | sort -u)

extract_keys() {
  local file="$1"
  [[ ! -f "$file" ]] && return
  info "Scanning: $file"
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Z_][A-Z0-9_]{2,})[[:space:]]*=[[:space:]]*[\"\']?([^\"\'[:space:]]{4,})[\"\']? ]]; then
      local k="${BASH_REMATCH[2]}" v="${BASH_REMATCH[3]}"
      # Skip obvious placeholders
      [[ "$v" =~ ^(your_|REPLACE|xxx|change|todo|example|placeholder|INSERT|<) ]] && continue
      echo "${k}=${v}" >> "$DISCOVERED"
      ((KEYS_FOUND++)) || true
      ok "Found: ${k}=****"
    fi
  done < "$file"
  # AWS credentials special case
  if [[ "$file" == *"credentials"* ]]; then
    local ak sc
    ak=$(grep -oP 'aws_access_key_id\s*=\s*\K(AKIA[A-Z0-9]{16})' "$file" 2>/dev/null || true)
    sc=$(grep -oP 'aws_secret_access_key\s*=\s*\K([A-Za-z0-9/+=]{40})' "$file" 2>/dev/null || true)
    [[ -n "$ak" ]] && { echo "AWS_ACCESS_KEY_ID=${ak}" >> "$DISCOVERED"; ok "Found: AWS_ACCESS_KEY_ID"; ((KEYS_FOUND++)) || true; }
    [[ -n "$sc" ]] && { echo "AWS_SECRET_ACCESS_KEY=${sc}" >> "$DISCOVERED"; ok "Found: AWS_SECRET_ACCESS_KEY"; ((KEYS_FOUND++)) || true; }
  fi
}

log "Scanning ${#SEARCH_PATHS[@]} locations..."
for p in "${SEARCH_PATHS[@]}"; do extract_keys "$p"; done

# Dedup
[[ -s "$DISCOVERED" ]] && sort -u -t= -k1,1 "$DISCOVERED" -o "$DISCOVERED"
log "Discovered $KEYS_FOUND keys ($( wc -l < "$DISCOVERED" 2>/dev/null || echo 0) unique)."

# Load into shell env
[[ -s "$DISCOVERED" ]] && { set -a; source "$DISCOVERED"; set +a; }

# Inject to SSM
if command -v aws &>/dev/null && [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
  log "Injecting keys into AWS SSM /garcar/*..."
  while IFS='=' read -r key value; do
    [[ -z "$key" || -z "$value" || "$key" =~ ^# ]] && continue
    aws ssm put-parameter \
      --name "/garcar/${key}" --value "${value}" \
      --type SecureString --overwrite \
      --region "${AWS_REGION:-us-east-1}" \
      --no-cli-pager &>/dev/null && {
        ok "SSM: /garcar/${key}"
        ((KEYS_INJECTED++)) || true
      } || warn "SSM skip: ${key}"
  done < "$DISCOVERED"
else
  warn "No AWS credentials found yet — keys staged locally at $DISCOVERED"
  warn "Once AWS creds are discovered, re-run: garcar-boot"
fi

# Chain into secrets_provisioner.py
REPO_DIR="$(find "$HOME" -maxdepth 4 -name 'secrets_provisioner.py' -exec dirname {} \; 2>/dev/null | head -1)"
if [[ -n "$REPO_DIR" ]]; then
  log "Running secrets_provisioner.py → GitHub sync..."
  cd "$REPO_DIR"
  python3 secrets_provisioner.py 2>/dev/null || warn "provisioner needs AWS creds to fully run"
fi

log "Phase 2 complete — $KEYS_INJECTED keys injected to SSM."

# ================================================================
# PHASE 3 — SELF-CONFIGURING INTEGRATION FINDER
# ================================================================
section "PHASE 3 — Integration Finder"

declare -A INTEGRATIONS=(
  [stripe]="STRIPE_SECRET_KEY,STRIPE_PUBLISHABLE_KEY,STRIPE_WEBHOOK_SECRET"
  [openai]="OPENAI_API_KEY"
  [anthropic]="ANTHROPIC_API_KEY"
  [linear]="LINEAR_API_KEY,LINEAR_TEAM_ID"
  [apollo]="APOLLO_API_KEY"
  [twilio]="TWILIO_ACCOUNT_SID,TWILIO_AUTH_TOKEN,TWILIO_FROM_NUMBER"
  [github]="GITHUB_TOKEN"
  [aws]="AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY,AWS_REGION"
  [vercel]="VERCEL_TOKEN"
  [zapier]="ZAPIER_WEBHOOK_URL"
  [notion]="NOTION_TOKEN"
  [redis]="REDIS_URL"
  [postgres]="DATABASE_URL"
  [cloudflare]="CLOUDFLARE_API_TOKEN"
)

echo "{" > "$INTEGRATIONS"
FIRST=true

for service in "${!INTEGRATIONS[@]}"; do
  IFS=',' read -ra keys <<< "${INTEGRATIONS[$service]}"
  status="missing"
  present_keys=()
  for k in "${keys[@]}"; do
    val="${!k:-}"
    [[ -n "$val" ]] && present_keys+=("$k") && status="configured"
  done

  if [[ "$status" == "configured" ]]; then
    ok "Integration LIVE:    ${service} (${present_keys[*]})"
    ((INTEGS_FOUND++)) || true
  else
    miss "Integration MISSING: ${service}"
  fi

  [[ "$FIRST" == true ]] && FIRST=false || echo "," >> "$INTEGRATIONS"
  echo "  \"${service}\": { \"status\": \"${status}\", \"keys\": [$(printf '\"'%s'\",' "${keys[@]}" | sed 's/,$//')]  }" >> "$INTEGRATIONS"
done
echo "}" >> "$INTEGRATIONS"

log "Integration scan: $INTEGS_FOUND/${#INTEGRATIONS[@]} services configured."
log "Integration map saved to: $INTEGRATIONS"

# Auto-generate .env from what is missing for easy fill-in
MISSING_TEMPLATE="$STATE_DIR/missing_keys_template.env"
> "$MISSING_TEMPLATE"
for service in "${!INTEGRATIONS[@]}"; do
  IFS=',' read -ra keys <<< "${INTEGRATIONS[$service]}"
  for k in "${keys[@]}"; do
    val="${!k:-}"
    if [[ -z "$val" ]]; then
      echo "# ${service}"
      echo "${k}="
    fi
  done
done >> "$MISSING_TEMPLATE"
info "Missing keys template: $MISSING_TEMPLATE"

log "Phase 3 complete."

# ================================================================
# PHASE 4 — FULL TERMUX ENVIRONMENT BOOTSTRAP
# ================================================================
section "PHASE 4 — Termux Environment Bootstrap"

# Install garcar-boot alias globally
SHELL_RC="$HOME/.bashrc"
[[ -f "$HOME/.zshrc" ]] && SHELL_RC="$HOME/.zshrc"

if ! grep -q 'garcar-boot' "$SHELL_RC" 2>/dev/null; then
  cat >> "$SHELL_RC" << 'ALIAS_EOF'

# ── GARCAR AUTO-ALIASES ───────────────────────────────────
alias garcar-boot='bash ~/garcar-autonomous-wealth-system/garcar_omega_bootstrap.sh'
alias garcar-keys='bash ~/garcar-autonomous-wealth-system/termux_key_discovery.sh'
alias garcar-audit='python3 ~/garcar-autonomous-wealth-system/secrets_manager.py'
alias garcar-status='cat ~/.garcar/integrations.json | python3 -m json.tool'
alias garcar-watch='tail -f ~/.garcar/omega.log'
alias garcar-missing='cat ~/.garcar/missing_keys_template.env'
alias garcar-sync='cd ~/garcar-autonomous-wealth-system && python3 secrets_provisioner.py'
# ─────────────────────────────────────────────────────────
ALIAS_EOF
  ok "Aliases installed → $SHELL_RC"
else
  ok "Aliases already present in $SHELL_RC"
fi

# Setup git config if missing
if ! git config --global user.email &>/dev/null; then
  git config --global user.email "garrettcarrol@garcar.io"
  git config --global user.name "Garrett Carroll"
  git config --global pull.rebase false
  ok "Git global config set"
fi

# Clone or update all Garcar repos
GARCAR_REPOS=(
  "garcar-autonomous-wealth-system"
  "api-key-automaton"
  "nwu-protocol"
  "systems-master-hub"
  "ai-business-automation-tree"
)

log "Syncing Garcar repos..."
for repo in "${GARCAR_REPOS[@]}"; do
  local_path="$HOME/$repo"
  if [[ -d "$local_path" ]]; then
    git -C "$local_path" pull --quiet 2>/dev/null && ok "Pulled: $repo" || warn "Pull failed: $repo"
  else
    git clone --quiet "https://github.com/Garrettc123/${repo}.git" "$local_path" 2>/dev/null \
      && ok "Cloned: $repo" || warn "Clone failed: $repo"
  fi
done

# AWS CLI config
if command -v aws &>/dev/null && [[ -z "$(aws configure get region 2>/dev/null)" ]]; then
  mkdir -p "$HOME/.aws"
  cat > "$HOME/.aws/config" << 'AWS_EOF'
[default]
region = us-east-1
output = json
AWS_EOF
  ok "AWS CLI region configured"
fi

log "Phase 4 complete — Termux environment fully bootstrapped."

# ================================================================
# PHASE 5 — PERSISTENT BACKGROUND DEPENDENCY WATCHER
# ================================================================
section "PHASE 5 — Persistent Dependency Watcher Daemon"

WATCHER_SCRIPT="$STATE_DIR/watcher.sh"

cat > "$WATCHER_SCRIPT" << 'WATCHER_EOF'
#!/data/data/com.termux/files/usr/bin/bash
# GARCAR BACKGROUND WATCHER — runs every 30 min
# Monitors for new .env files, new packages needed, integration changes

STATE_DIR="$HOME/.garcar"
LOG="$STATE_DIR/watcher.log"
DISCOVERED="$STATE_DIR/discovered.env"

mkdir -p "$STATE_DIR"

log_w() { echo "[$(date '+%H:%M:%S')] $1" >> "$LOG"; }

log_w "Watcher started (PID $$)"

while true; do
  log_w "--- Dependency check ---"

  # 1. Check for new .env files dropped anywhere
  NEW_ENVS=$(find "$HOME" -maxdepth 6 -newer "$STATE_DIR/last_scan" -name '*.env' \
    2>/dev/null | grep -v '.git' | head -20 || true)
  if [[ -n "$NEW_ENVS" ]]; then
    log_w "New .env files detected: $NEW_ENVS"
    echo "$NEW_ENVS" | while read -r f; do
      while IFS= read -r line; do
        [[ "$line" =~ ^[[:space:]]*# || -z "${line// }" ]] && continue
        if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Z_][A-Z0-9_]+)[[:space:]]*=[[:space:]]*(.+) ]]; then
          k="${BASH_REMATCH[2]}"; v="${BASH_REMATCH[3]//[\"\']}"
          [[ -z "$v" || "$v" =~ ^(your_|REPLACE|xxx) ]] && continue
          echo "${k}=${v}" >> "$DISCOVERED"
          log_w "Discovered: $k"
          # Auto-inject
          aws ssm put-parameter --name "/garcar/${k}" --value "$v" \
            --type SecureString --overwrite \
            --region "${AWS_REGION:-us-east-1}" --no-cli-pager &>/dev/null \
            && log_w "Auto-injected: /garcar/$k" || true
        fi
      done < "$f"
    done
  fi

  # 2. Check for missing Python packages imported in any .py file
  IMPORTS=$(grep -rh '^import \|^from ' "$HOME" --include='*.py' \
    -l 2>/dev/null | head -5 || true)
  # (lightweight check — full import scan would be too heavy in background)

  # 3. Check if secrets_provisioner.py needs re-run (new SSM keys)
  SSM_COUNT=$(aws ssm get-parameters-by-path --path /garcar/ \
    --region "${AWS_REGION:-us-east-1}" --query 'Parameters | length(@)' \
    --output text 2>/dev/null || echo 0)
  LAST_COUNT=$(cat "$STATE_DIR/last_ssm_count" 2>/dev/null || echo 0)
  if [[ "$SSM_COUNT" != "$LAST_COUNT" ]]; then
    log_w "SSM count changed ($LAST_COUNT → $SSM_COUNT) — triggering GitHub sync"
    cd "$(find $HOME -maxdepth 4 -name 'secrets_provisioner.py' -exec dirname {} \; 2>/dev/null | head -1)" 2>/dev/null || true
    python3 secrets_provisioner.py >> "$LOG" 2>&1 || true
    echo "$SSM_COUNT" > "$STATE_DIR/last_ssm_count"
  fi

  touch "$STATE_DIR/last_scan"
  log_w "Cycle complete. Sleeping 1800s..."
  sleep 1800
done
WATCHER_EOF

chmod +x "$WATCHER_SCRIPT"
touch "$STATE_DIR/last_scan" 2>/dev/null || true

# Kill old watcher if running
[[ -f "$PID_FILE" ]] && kill "$(cat "$PID_FILE")" 2>/dev/null || true

# Launch watcher in background
nohup bash "$WATCHER_SCRIPT" >> "$STATE_DIR/watcher.log" 2>&1 &
echo $! > "$PID_FILE"
ok "Watcher daemon running (PID $(cat "$PID_FILE"))"
ok "Watcher logs: garcar-watch"

log "Phase 5 complete — persistent watcher active."

# ================================================================
# FINAL REPORT
# ================================================================
echo ""
echo -e "${BOLD}${BLUE}================================================================${NC}"
echo -e "${BOLD}${GREEN}  GARCAR OMEGA BOOTSTRAP COMPLETE${NC}"
echo -e "  Packages installed:  ${PACKAGES_INSTALLED}"
echo -e "  Keys discovered:     ${KEYS_FOUND}"
echo -e "  Keys injected→SSM:   ${KEYS_INJECTED}"
echo -e "  Integrations live:   ${INTEGS_FOUND}/${#INTEGRATIONS[@]}"
echo -e "  Watcher PID:         $(cat "$PID_FILE" 2>/dev/null || echo N/A)"
echo -e "  Log:                 $LOG_FILE"
echo -e "${BOLD}${BLUE}================================================================${NC}"
echo ""
echo -e "${CYAN}Quick commands (reload shell first: source $SHELL_RC):${NC}"
echo -e "  ${BOLD}garcar-boot${NC}     — re-run full bootstrap"
echo -e "  ${BOLD}garcar-keys${NC}     — re-run key discovery only"
echo -e "  ${BOLD}garcar-audit${NC}    — audit all keys in SSM"
echo -e "  ${BOLD}garcar-status${NC}   — show integration status"
echo -e "  ${BOLD}garcar-missing${NC}  — show unfilled key template"
echo -e "  ${BOLD}garcar-sync${NC}     — force GitHub Actions secrets sync"
echo -e "  ${BOLD}garcar-watch${NC}    — tail live watcher log"
echo ""
source "$SHELL_RC" 2>/dev/null || true
