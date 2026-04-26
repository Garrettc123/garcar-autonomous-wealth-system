#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# GARCAR TERMUX BOOTSTRAP — One command, zero manual entry
# Installs deps + runs key discovery + injects to SSM
# Run once in Termux: curl -sL https://raw.githubusercontent.com/Garrettc123/garcar-autonomous-wealth-system/main/termux_setup.sh | bash
# ============================================================

set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[GARCAR BOOT]${NC} $1"; }
info() { echo -e "${CYAN}[INFO]${NC}       $1"; }

log "Installing Termux dependencies..."
pkg update -y -q
pkg install -y -q python git curl jq openssh

log "Installing Python packages..."
pip install --quiet boto3 requests awscli pynacl

# Clone or pull repo
REPO_DIR="$HOME/garcar-autonomous-wealth-system"
if [[ -d "$REPO_DIR" ]]; then
  log "Pulling latest from repo..."
  git -C "$REPO_DIR" pull --quiet
else
  log "Cloning garcar-autonomous-wealth-system..."
  git clone --quiet https://github.com/Garrettc123/garcar-autonomous-wealth-system.git "$REPO_DIR"
fi

cd "$REPO_DIR"
chmod +x termux_key_discovery.sh

log "Running auto key discovery + injection..."
bash termux_key_discovery.sh

log ""
log "GARCAR BOOT COMPLETE — all keys auto-injected, systems are live."
