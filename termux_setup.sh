#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# GARCAR TERMUX BOOTSTRAP v2.1 — Fixed for Python 3.13 + ARM64
# Fixes: pynacl build failure, repo clone path, edge-node setup
# Run: curl -sL https://raw.githubusercontent.com/Garrettc123/garcar-autonomous-wealth-system/main/termux_setup.sh | bash
# ============================================================

set -uo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[GARCAR BOOT]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC}       $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}       $1"; }
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC}        $1"; }

log "Installing Termux system packages..."
pkg update -y -q 2>/dev/null || true
pkg install -y -q python git curl jq openssh libsodium libffi openssl clang make 2>/dev/null || true

# ── PYNACL FIX: Python 3.13 + ARM64 ─────────────────────────────────
# pynacl from pip tries to compile libsodium from source on ARM64
# which fails on Python 3.13 due to setuptools deprecation.
# FIX: install libsodium system pkg first, then install pynacl
# with SODIUM_INSTALL=system to skip the compile entirely.
log "Installing pynacl (ARM64 Python 3.13 fix)..."
if python3 -c "import nacl" &>/dev/null 2>&1; then
  ok "pynacl already installed"
else
  # Ensure libsodium headers are present
  pkg install -y -q libsodium 2>/dev/null || true
  # Use pre-built wheel if available, fallback to system sodium
  SODIUM_INSTALL=system pip install --quiet pynacl 2>/dev/null || \
  pip install --quiet --only-binary=:all: pynacl 2>/dev/null || \
  pip install --quiet pynacl --no-build-isolation 2>/dev/null || {
    warn "pynacl binary install failed — trying pure-python cryptography fallback"
    pip install --quiet cryptography 2>/dev/null || true
  }
fi

log "Installing remaining Python packages..."
for pkg_name in boto3 requests awscli fastapi uvicorn stripe openai python-dotenv rich httpx; do
  python3 -c "import ${pkg_name//-/_}" &>/dev/null 2>&1 && ok "$pkg_name" || \
    pip install --quiet "$pkg_name" 2>/dev/null && ok "Installed: $pkg_name" || \
    warn "Could not install: $pkg_name"
done

# ── CLONE / PULL ALL GARCAR REPOS ────────────────────────────────────
GARCAR_REPOS=(
  "garcar-autonomous-wealth-system"
  "api-key-automaton"
  "nwu-protocol"
  "systems-master-hub"
  "edge-node"
)

log "Syncing Garcar repos to $HOME..."
for repo in "${GARCAR_REPOS[@]}"; do
  dest="$HOME/$repo"
  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" pull --quiet 2>/dev/null && ok "Pulled: $repo" || warn "Pull failed: $repo"
  else
    git clone --quiet "https://github.com/Garrettc123/${repo}.git" "$dest" 2>/dev/null \
      && ok "Cloned: $repo" \
      || warn "Clone failed (may not exist yet): $repo"
  fi
done

REPO_DIR="$HOME/garcar-autonomous-wealth-system"
[[ ! -d "$REPO_DIR" ]] && { err "Main repo not found at $REPO_DIR — aborting"; exit 1; }

cd "$REPO_DIR"
chmod +x termux_key_discovery.sh garcar_omega_bootstrap.sh 2>/dev/null || true

# ── EDGE-NODE ENVIRONMENT SETUP ──────────────────────────────────────
EDGE_DIR="$HOME/edge-node"
if [[ -d "$EDGE_DIR" ]]; then
  log "Setting up edge-node environment..."
  mkdir -p "$EDGE_DIR/config" "$EDGE_DIR/logs" "$EDGE_DIR/scripts"

  # Create .env template if missing
  if [[ ! -f "$EDGE_DIR/config/.env" ]]; then
    cat > "$EDGE_DIR/config/.env" << 'ENV_EOF'
# ─── GARCAR EDGE NODE CONFIG ───────────────────────────────
# Fill in values then run: garcar-boot

# Stripe
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=

# OpenAI / Anthropic
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Linear
LINEAR_API_KEY=
LINEAR_TEAM_ID=

# AWS
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1

# GitHub
GITHUB_TOKEN=

# Notion
NOTION_TOKEN=

# Edge node identity
EDGE_NODE_ID=pixel10-garcar
EDGE_NODE_ENV=production
ENV_EOF
    ok "Created edge-node config template: $EDGE_DIR/config/.env"
    warn "ACTION REQUIRED: nano $EDGE_DIR/config/.env  — fill in your API keys"
  else
    ok "edge-node config already exists"
    # Merge edge-node keys into discovery
    cp "$EDGE_DIR/config/.env" "$HOME/.env.garcar-edge" 2>/dev/null || true
  fi

  # Make watchdog executable
  [[ -f "$EDGE_DIR/scripts/watchdog.sh" ]] && chmod +x "$EDGE_DIR/scripts/watchdog.sh" && ok "watchdog.sh +x"
fi

# ── SSH KEY: inject PIXEL10_SSH_KEY into GitHub Secrets via SSM ───────
SSH_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICIKH5AUMMnbtOOC76DRolIewULvxpxtqyqS+X3GC0kM garcar-edge-20260426"

log "Injecting PIXEL10_SSH_KEY into SSM and GitHub secrets..."

# Save to authorized_keys so edge node can receive inbound connections
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if ! grep -qF "garcar-edge-20260426" "$HOME/.ssh/authorized_keys" 2>/dev/null; then
  echo "$SSH_KEY" >> "$HOME/.ssh/authorized_keys"
  chmod 600 "$HOME/.ssh/authorized_keys"
  ok "SSH key added to authorized_keys"
fi

# Inject to SSM
if command -v aws &>/dev/null && [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
  aws ssm put-parameter \
    --name "/garcar/PIXEL10_SSH_KEY" \
    --value "$SSH_KEY" \
    --type SecureString --overwrite \
    --region "${AWS_REGION:-us-east-1}" \
    --no-cli-pager 2>/dev/null && ok "SSM: /garcar/PIXEL10_SSH_KEY" || warn "SSM inject failed"
else
  # Stage it for when AWS creds are available
  echo "PIXEL10_SSH_KEY=${SSH_KEY}" >> "$HOME/.garcar/discovered.env" 2>/dev/null || true
  warn "AWS creds not yet available — SSH key staged for auto-injection by watcher"
fi

# ── RUN KEY DISCOVERY + INJECTION ────────────────────────────────────
log "Running auto key discovery + injection..."
bash "$REPO_DIR/termux_key_discovery.sh"

# ── TERMUX:BOOT PERSISTENCE SETUP ────────────────────────────────────
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"
cat > "$BOOT_DIR/garcar-autostart.sh" << 'BOOT_EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Runs automatically on device reboot via Termux:Boot
# Install Termux:Boot from F-Droid for this to activate

# Give Android 10s to finish booting
sleep 10

# Start SSH server
sshd 2>/dev/null || true

# Start edge-node watchdog
[[ -f "$HOME/edge-node/scripts/watchdog.sh" ]] && \
  nohup bash "$HOME/edge-node/scripts/watchdog.sh" \
  >> "$HOME/edge-node/logs/watchdog.log" 2>&1 &

# Restart garcar watcher daemon
[[ -f "$HOME/.garcar/watcher.sh" ]] && \
  nohup bash "$HOME/.garcar/watcher.sh" \
  >> "$HOME/.garcar/watcher.log" 2>&1 &

echo "[$(date)] Garcar autostart complete" >> "$HOME/.garcar/boot.log"
BOOT_EOF
chmod +x "$BOOT_DIR/garcar-autostart.sh"
ok "Termux:Boot script installed → $BOOT_DIR/garcar-autostart.sh"
warn "Install Termux:Boot from F-Droid if not already installed — then reboot persistence is ACTIVE"

# ── FINAL REPORT ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  GARCAR BOOT v2.1 COMPLETE — $(date)"
echo "============================================================"
echo ""
echo "  Next steps:"
echo "  1. nano $EDGE_DIR/config/.env    ← fill API keys"
echo "  2. Install Termux:Boot (F-Droid) ← reboot persistence"
echo "  3. bash $EDGE_DIR/scripts/watchdog.sh"
echo "  4. tail -f $EDGE_DIR/logs/watchdog.log"
echo ""
echo "  Quick commands (run: source ~/.bashrc first):"
echo "  garcar-boot    garcar-status    garcar-missing    garcar-watch"
echo "============================================================"
