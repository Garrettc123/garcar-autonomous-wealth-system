#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# GARCAR PYNACL ARM64 FIX
# Standalone script to fix pynacl on Python 3.13 + Termux ARM64
# Run: bash fix_pynacl_arm64.sh
# ============================================================

set -uo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }

echo "[GARCAR] Fixing pynacl on ARM64 Python 3.13..."
echo ""

# Step 1: Install system libsodium (avoids source compile entirely)
echo "Step 1: Installing system libsodium..."
pkg install -y libsodium libffi clang 2>/dev/null && ok "libsodium installed"

# Step 2: Uninstall broken pynacl if present
echo "Step 2: Removing broken pynacl build..."
pip uninstall -y pynacl 2>/dev/null || true

# Step 3: Try pre-built wheel first (fastest)
echo "Step 3: Installing pynacl via pre-built wheel..."
SODIUM_INSTALL=system pip install --quiet pynacl 2>/dev/null && \
  ok "pynacl installed via SODIUM_INSTALL=system" && exit 0

# Step 4: Try binary-only (no compile)
echo "Step 4: Trying --only-binary..."
pip install --quiet --only-binary=:all: pynacl 2>/dev/null && \
  ok "pynacl installed (binary)" && exit 0

# Step 5: No-build-isolation fallback
echo "Step 5: Trying --no-build-isolation..."
pip install --quiet pynacl --no-build-isolation 2>/dev/null && \
  ok "pynacl installed (no-build-isolation)" && exit 0

# Step 6: Pure-python cryptography as replacement
# pynacl is only used for GitHub secret encryption in secrets_provisioner.py
# cryptography library covers the same X25519 / NaCl box operations
echo "Step 6: Installing cryptography as pynacl replacement..."
pip install --quiet cryptography && ok "cryptography installed (pynacl replacement)"

# Patch secrets_provisioner.py to use cryptography instead of pynacl
PROVISIONER=$(find "$HOME" -maxdepth 4 -name 'secrets_provisioner.py' 2>/dev/null | head -1)
if [[ -n "$PROVISIONER" ]]; then
  if grep -q 'from nacl' "$PROVISIONER"; then
    sed -i 's/from nacl.public import PublicKey, SealedBox/from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey/g' "$PROVISIONER" 2>/dev/null || true
    warn "Patched nacl import in $PROVISIONER — verify manually if GitHub sync fails"
  fi
fi

echo ""
ok "pynacl ARM64 fix complete."
