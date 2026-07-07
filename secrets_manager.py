# secrets_manager.py — Garcar Auto API Secrets System
# Single source of truth for all API keys across every module.
# Priority: AWS Secrets Manager → GitHub Actions env → .env file → error

import os
import json
import boto3
from functools import lru_cache
from typing import Optional, Dict

# ── Secret Registry ─────────────────────────────────────────────────────────────────
# All secrets this system uses, with their AWS Secrets Manager key name.
# Format: ENV_VAR_NAME -> AWS_SECRET_KEY (or None if env-only)
SECRET_REGISTRY: Dict[str, Optional[str]] = {
    # AWS Core
    "AWS_REGION":                    None,   # env only
    "AWS_ACCOUNT_ID":                None,
    "S3_BUCKET":                     "garcar/aws/s3_bucket",
    "KMS_KEY_ID":                    "garcar/aws/kms_key_id",
    "LAMBDA_EXECUTION_ROLE_ARN":     "garcar/aws/lambda_role_arn",
    # Stripe
    "STRIPE_SECRET_KEY":             "garcar/stripe/secret_key",
    "STRIPE_PUBLISHABLE_KEY":        "garcar/stripe/publishable_key",
    "STRIPE_WEBHOOK_SECRET":         "garcar/stripe/webhook_secret",
    "STRIPE_PRICE_BASIC":            "garcar/stripe/price_basic",
    "STRIPE_PRICE_PRO":              "garcar/stripe/price_pro",
    "STRIPE_PRICE_ENTERPRISE":       "garcar/stripe/price_enterprise",
    # Apollo Lead Gen
    "APOLLO_API_KEY":                "garcar/apollo/api_key",
    # OpenAI
    "OPENAI_API_KEY":                "garcar/openai/api_key",
    # AWS SES
    "SES_SENDER_EMAIL":              "garcar/ses/sender_email",
    # Twilio SMS
    "TWILIO_ACCOUNT_SID":            "garcar/twilio/account_sid",
    "TWILIO_AUTH_TOKEN":             "garcar/twilio/auth_token",
    "TWILIO_FROM_NUMBER":            "garcar/twilio/from_number",
    # Linear
    "LINEAR_API_KEY":                "garcar/linear/api_key",
    "LINEAR_TEAM_ID":                "garcar/linear/team_id",
    # Dashboard
    "DASHBOARD_API_KEY":             "garcar/dashboard/api_key",
    "DASHBOARD_URL":                 None,
    "UPGRADE_URL":                   None,
    # Fulfillment
    "FULFILLMENT_WEBHOOK_URL":       "garcar/fulfillment/webhook_url",
    "FULFILLMENT_WEBHOOK_SECRET":    "garcar/fulfillment/webhook_secret",
}

REQUIRED_SECRETS = [
    "STRIPE_SECRET_KEY",
    "APOLLO_API_KEY",
    "OPENAI_API_KEY",
    "SES_SENDER_EMAIL",
    "AWS_REGION",
]

AWS_SECRET_NAME = os.environ.get("AWS_SECRET_BUNDLE_NAME", "garcar/all")
FULFILLMENT_WEBHOOK_URL_KEY = "FULFILLMENT_WEBHOOK_URL"
FULFILLMENT_WEBHOOK_SECRET_KEY = "FULFILLMENT_WEBHOOK_SECRET"


# ── Loader ───────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_aws_bundle() -> Dict[str, str]:
    """Fetch the full garcar/all secret bundle from AWS Secrets Manager once."""
    try:
        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
        response = client.get_secret_value(SecretId=AWS_SECRET_NAME)
        return json.loads(response["SecretString"])
    except Exception as e:
        # Gracefully degrade — fall back to env vars
        return {}


def get(key: str, required: bool = False) -> Optional[str]:
    """
    Retrieve a secret by env var name.
    Priority: env var → AWS bundle → None/raise
    """
    # 1. Direct env var (set by GitHub Actions, .env, or system)
    value = os.environ.get(key)
    if value:
        return value

    # 2. AWS Secrets Manager bundle
    bundle = _load_aws_bundle()
    aws_key = SECRET_REGISTRY.get(key)
    if aws_key:
        # Try full path key first, then short name
        short = aws_key.split("/")[-1].upper()
        value = bundle.get(aws_key) or bundle.get(short) or bundle.get(key)
        if value:
            os.environ[key] = value  # Cache into env for subsequent calls
            return value

    if required:
        raise EnvironmentError(
            f"[SecretsManager] Required secret '{key}' not found in env or AWS Secrets Manager. "
            f"Add it as a GitHub Secret or to the '{AWS_SECRET_NAME}' bundle."
        )
    return None


def require(key: str) -> str:
    """Get a secret or raise immediately. Use for critical keys."""
    return get(key, required=True)


def audit() -> Dict[str, str]:
    """Check all registry keys and return status dict."""
    results = {}
    for key in SECRET_REGISTRY:
        val = get(key)
        if val:
            masked = val[:4] + "****" if len(val) > 4 else "****"
            results[key] = f"OK ({masked})"
        else:
            results[key] = "MISSING"
    return results


def print_audit():
    """Pretty-print secrets audit to stdout."""
    print("\n" + "="*56)
    print("  🔑 GARCAR SECRETS AUDIT")
    print("="*56)
    results = audit()
    ok = missing = 0
    for key, status in results.items():
        icon = "✅" if status.startswith("OK") else "❌"
        print(f"  {icon}  {key:<38}  {status}")
        if status.startswith("OK"):
            ok += 1
        else:
            missing += 1
    print("="*56)
    print(f"  Total: {ok + missing} | ✅ Found: {ok} | ❌ Missing: {missing}")
    print("="*56 + "\n")
    return missing == 0


if __name__ == "__main__":
    all_present = print_audit()
    exit(0 if all_present else 1)
