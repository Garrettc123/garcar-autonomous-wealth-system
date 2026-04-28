#!/usr/bin/env python3
"""
Garcar Enterprise — AUTO KEY PROVISIONER
=========================================
Reads your .env file and auto-provisions EVERY secret
directly into GitHub Actions Secrets via the GitHub API.

Usage:
    1. cp .env.example .env
    2. Fill in all values in .env
    3. python setup_secrets.py

Requires:
    pip install requests PyNaCl python-dotenv
    Set GITHUB_TOKEN env var (PAT with repo + admin:repo_hook scope)
"""

import os
import sys
import base64
import json
import requests
from pathlib import Path

try:
    from nacl import public, encoding
except ImportError:
    print("\n❌ Missing PyNaCl. Run: pip install PyNaCl")
    sys.exit(1)

try:
    from dotenv import dotenv_values
except ImportError:
    print("\n❌ Missing python-dotenv. Run: pip install python-dotenv")
    sys.exit(1)


# ─── CONFIG ───────────────────────────────────────────────────────────────────
REPO_OWNER = "Garrettc123"
REPO_NAME  = "garcar-autonomous-wealth-system"
ENV_FILE   = ".env"

# All secrets required by the 5 GitHub Actions workflows
REQUIRED_SECRETS = [
    # Stripe
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_BASIC",
    "STRIPE_PRICE_PRO",
    "STRIPE_PRICE_ENTERPRISE",
    # Linear
    "LINEAR_API_KEY",
    "LINEAR_TEAM_ID",
    "LINEAR_REVENUE_LABEL",
    # Apollo
    "APOLLO_API_KEY",
    # AI
    "OPENAI_API_KEY",
    # AWS
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "AWS_ACCOUNT_ID",
    "S3_BUCKET",
    # Email
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASS",
    "SES_SENDER_EMAIL",
    # Twilio / SMS
    "TWILIO_SID",
    "TWILIO_TOKEN",
    "TWILIO_FROM",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM_NUMBER",
    # Notion
    "NOTION_TOKEN",
    # Redis
    "REDIS_URL",
    # HubSpot
    "HUBSPOT_API_KEY",
    # Railway
    "RAILWAY_TOKEN",
    # GitHub PAT (for cross-repo triggers)
    "GH_PAT",
    # Dashboard
    "DASHBOARD_API_KEY",
]


# ─── GITHUB API HELPERS ───────────────────────────────────────────────────────
def get_public_key(token: str, owner: str, repo: str) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key"
    r = requests.get(url, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json()


def encrypt_secret(public_key_value: str, secret_value: str) -> str:
    """Encrypt secret using repo's libsodium public key."""
    pk_bytes = base64.b64decode(public_key_value)
    pk = public.PublicKey(pk_bytes)
    box = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def set_secret(token: str, owner: str, repo: str, key_id: str, name: str, encrypted_value: str) -> bool:
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{name}"
    payload = {"encrypted_value": encrypted_value, "key_id": key_id}
    r = requests.put(
        url,
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        json=payload
    )
    return r.status_code in (201, 204)


def list_existing_secrets(token: str, owner: str, repo: str) -> list:
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets"
    r = requests.get(url, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
    if r.status_code == 200:
        return [s['name'] for s in r.json().get('secrets', [])]
    return []


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("\n🔐 GARCAR AUTO KEY PROVISIONER")
    print("=" * 50)

    # 1. Get GitHub token
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
    if not github_token:
        print("\n❌ Set GITHUB_TOKEN environment variable first.")
        print("  export GITHUB_TOKEN=ghp_yourPersonalAccessToken")
        print("  (Needs: repo, admin:repo_hook, workflow scopes)")
        sys.exit(1)

    # 2. Load .env file
    env_path = Path(ENV_FILE)
    if not env_path.exists():
        print(f"\n❌ {ENV_FILE} not found. Run: cp .env.example .env && fill it in.")
        sys.exit(1)

    env_values = dotenv_values(ENV_FILE)
    print(f"\n✅ Loaded {len(env_values)} values from {ENV_FILE}")

    # 3. Get repo public key for encryption
    print(f"\n🔍 Fetching GitHub repo public key for {REPO_OWNER}/{REPO_NAME}...")
    try:
        pub_key_data = get_public_key(github_token, REPO_OWNER, REPO_NAME)
        key_id = pub_key_data['key_id']
        key_value = pub_key_data['key']
        print(f"✅ Repo public key: {key_id}")
    except Exception as e:
        print(f"❌ Failed to fetch public key: {e}")
        sys.exit(1)

    # 4. Check existing secrets
    existing = list_existing_secrets(github_token, REPO_OWNER, REPO_NAME)
    print(f"\n📦 Existing secrets in repo: {len(existing)}")

    # 5. Provision all secrets
    print("\n🚀 Provisioning secrets...")
    print("-" * 50)

    results = {"set": [], "skipped_empty": [], "already_exists": [], "failed": []}

    for secret_name in REQUIRED_SECRETS:
        value = env_values.get(secret_name, "").strip()

        # Skip placeholder values
        if not value or value.startswith("your") or value.startswith("sk_test") or \
           value.startswith("pk_test") or value.startswith("ACyour") or \
           value in ["your-account-id", "your-kms-key-id"]:
            status = "⏭️  SKIP (placeholder)" if value else "⚠️  EMPTY"
            print(f"  {secret_name:35s}: {status}")
            results["skipped_empty"].append(secret_name)
            continue

        try:
            encrypted = encrypt_secret(key_value, value)
            success = set_secret(github_token, REPO_OWNER, REPO_NAME, key_id, secret_name, encrypted)
            if success:
                indicator = "🔄 UPDATE" if secret_name in existing else "✨ NEW"
                print(f"  {secret_name:35s}: ✅ {indicator}")
                results["set"].append(secret_name)
            else:
                print(f"  {secret_name:35s}: ❌ FAILED")
                results["failed"].append(secret_name)
        except Exception as e:
            print(f"  {secret_name:35s}: ❌ ERROR — {e}")
            results["failed"].append(secret_name)

    # 6. Summary report
    print("\n" + "=" * 50)
    print("GARCAR AUTO KEY — SUMMARY")
    print("=" * 50)
    print(f"  ✅ Set/Updated : {len(results['set'])} secrets")
    print(f"  ⏭️  Skipped      : {len(results['skipped_empty'])} (empty/placeholder)")
    print(f"  ❌ Failed       : {len(results['failed'])} secrets")

    if results["set"]:
        print(f"\n🟢 LIVE secrets provisioned:")
        for s in results["set"]:
            print(f"    • {s}")

    if results["skipped_empty"]:
        print(f"\n🟡 Still need values for:")
        for s in results["skipped_empty"]:
            print(f"    • {s}")

    if results["failed"]:
        print(f"\n🔴 Failed to set:")
        for s in results["failed"]:
            print(f"    • {s}")

    total_needed = len(REQUIRED_SECRETS)
    total_set = len(results["set"])
    pct = (total_set / total_needed) * 100
    print(f"\n🎯 Readiness: {total_set}/{total_needed} ({pct:.0f}%)")

    if pct == 100:
        print("\n🚀 ALL SYSTEMS GO — All 5 workflows fully armed!")
    elif pct >= 70:
        print("\n⚡ MOSTLY ARMED — Core workflows operational. Fill in remaining keys.")
    else:
        print("\n⚠️  Fill in .env values and re-run to complete provisioning.")

    print("\nView secrets: https://github.com/Garrettc123/garcar-autonomous-wealth-system/settings/secrets/actions")
    print("View Actions: https://github.com/Garrettc123/garcar-autonomous-wealth-system/actions\n")


if __name__ == "__main__":
    main()
