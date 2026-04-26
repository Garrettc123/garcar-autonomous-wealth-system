"""
withdrawal_agent.py — Garcar Enterprise
Autonomous Withdrawal Agent: sweeps available Stripe balance to your
linked bank account on a configurable schedule or threshold trigger.

Requires env vars:
  STRIPE_SECRET_KEY         — your Stripe secret key (sk_live_...)
  WITHDRAWAL_THRESHOLD      — USD cents minimum before sweep fires (default 5000 = $50)
  WITHDRAWAL_DESTINATION_ID — Stripe bank account / debit card ID (ba_... or card_...)
  WITHDRAWAL_CURRENCY       — default "usd"
  WITHDRAWAL_METHOD         — "standard" (1-3 days ACH) or "instant" (debit card, 1%)
  OWNER_EMAIL               — email to notify on each payout
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

try:
    import stripe
except ImportError:
    raise ImportError("Run: pip install stripe")

try:
    import requests
except ImportError:
    requests = None

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

THRESHOLD_CENTS    = int(os.environ.get("WITHDRAWAL_THRESHOLD", "5000"))   # $50.00
DESTINATION_ID     = os.environ.get("WITHDRAWAL_DESTINATION_ID", "")       # ba_... or card_...
CURRENCY           = os.environ.get("WITHDRAWAL_CURRENCY", "usd")
METHOD             = os.environ.get("WITHDRAWAL_METHOD", "standard")       # standard | instant
OWNER_EMAIL        = os.environ.get("OWNER_EMAIL", "")
LEDGER_PATH        = Path("withdrawal_ledger.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WITHDRAWAL] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("withdrawal_agent")


# ─────────────────────────────────────────────
# Ledger helpers
# ─────────────────────────────────────────────
def load_ledger() -> list:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_ledger(entries: list):
    LEDGER_PATH.write_text(json.dumps(entries, indent=2))


def record_payout(payout_obj: dict, available_cents: int, swept_cents: int):
    entries = load_ledger()
    entries.append({
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "payout_id":        payout_obj.get("id"),
        "status":           payout_obj.get("status"),
        "amount_cents":     swept_cents,
        "amount_usd":       swept_cents / 100,
        "available_before": available_cents,
        "currency":         CURRENCY,
        "method":           METHOD,
        "destination":      DESTINATION_ID,
        "arrival_date":     payout_obj.get("arrival_date"),
    })
    save_ledger(entries)
    log.info(f"Ledger updated — total entries: {len(entries)}")


# ─────────────────────────────────────────────
# Balance check
# ─────────────────────────────────────────────
def get_available_balance() -> int:
    """Returns available balance in cents for configured currency."""
    balance = stripe.Balance.retrieve()
    for entry in balance.available:
        if entry["currency"] == CURRENCY:
            return entry["amount"]
    return 0


# ─────────────────────────────────────────────
# Payout execution
# ─────────────────────────────────────────────
def execute_payout(amount_cents: int) -> dict:
    """
    Creates a Stripe Payout to the configured bank/debit destination.
    - method='standard'  → ACH, 1-3 business days, no fee
    - method='instant'   → Instant to debit card, arrives in ~30 min, 1% fee (min $0.50)
    """
    params = {
        "amount":      amount_cents,
        "currency":    CURRENCY,
        "method":      METHOD,
        "description": f"Garcar autonomous sweep {datetime.now(timezone.utc).date()}",
    }
    if DESTINATION_ID:
        params["destination"] = DESTINATION_ID

    payout = stripe.Payout.create(**params)
    log.info(
        f"Payout created: {payout['id']} | "
        f"${amount_cents/100:.2f} | status={payout['status']} | "
        f"arrival={payout.get('arrival_date')}"
    )
    return dict(payout)


# ─────────────────────────────────────────────
# Notification (optional webhook / email)
# ─────────────────────────────────────────────
def notify_owner(payout_id: str, amount_usd: float, status: str):
    """Best-effort notification — logs to console, optionally POSTs to a webhook."""
    msg = (
        f"💸 Garcar Payout Fired\n"
        f"  ID      : {payout_id}\n"
        f"  Amount  : ${amount_usd:.2f}\n"
        f"  Status  : {status}\n"
        f"  Method  : {METHOD}\n"
        f"  Time    : {datetime.now(timezone.utc).isoformat()}"
    )
    log.info(msg)

    webhook_url = os.environ.get("NOTIFICATION_WEBHOOK_URL", "")
    if webhook_url and requests:
        try:
            requests.post(webhook_url, json={"text": msg}, timeout=5)
        except Exception as exc:
            log.warning(f"Webhook notification failed: {exc}")


# ─────────────────────────────────────────────
# Safety checks
# ─────────────────────────────────────────────
def preflight_checks() -> bool:
    """Validate configuration before attempting any payout."""
    if not stripe.api_key or not stripe.api_key.startswith("sk_"):
        log.error("STRIPE_SECRET_KEY missing or invalid.")
        return False
    if not DESTINATION_ID:
        log.warning(
            "WITHDRAWAL_DESTINATION_ID not set — Stripe will use default payout destination."
        )
    if METHOD not in ("standard", "instant"):
        log.error(f"WITHDRAWAL_METHOD must be 'standard' or 'instant', got: {METHOD}")
        return False
    return True


# ─────────────────────────────────────────────
# Daily summary helper
# ─────────────────────────────────────────────
def print_summary():
    entries = load_ledger()
    total_swept = sum(e.get("amount_usd", 0) for e in entries)
    log.info(
        f"📊 Withdrawal Summary | "
        f"Total payouts: {len(entries)} | "
        f"Total swept: ${total_swept:.2f}"
    )


# ─────────────────────────────────────────────
# Main sweep function — call this from your scheduler
# ─────────────────────────────────────────────
def run_withdrawal_sweep(force: bool = False, override_amount_cents: int = 0):
    """
    Primary entry point.
    - force=True            : bypass threshold check, sweep whatever is available
    - override_amount_cents : sweep a specific amount instead of full balance
    """
    log.info("=== Withdrawal sweep starting ===")

    if not preflight_checks():
        log.error("Preflight failed — aborting sweep.")
        return {"status": "aborted", "reason": "preflight_failed"}

    available = get_available_balance()
    log.info(f"Available balance: ${available/100:.2f} | Threshold: ${THRESHOLD_CENTS/100:.2f}")

    if not force and available < THRESHOLD_CENTS:
        log.info(
            f"Balance ${available/100:.2f} below threshold ${THRESHOLD_CENTS/100:.2f} — skipping."
        )
        return {"status": "skipped", "available_cents": available}

    sweep_amount = override_amount_cents if override_amount_cents > 0 else available

    # Cap sweep to actual available balance
    sweep_amount = min(sweep_amount, available)

    if sweep_amount <= 0:
        log.info("Nothing to sweep.")
        return {"status": "skipped", "reason": "zero_balance"}

    try:
        payout = execute_payout(sweep_amount)
        record_payout(payout, available, sweep_amount)
        notify_owner(payout["id"], sweep_amount / 100, payout["status"])
        print_summary()
        return {
            "status":       "success",
            "payout_id":    payout["id"],
            "amount_usd":   sweep_amount / 100,
            "method":       METHOD,
            "arrival_date": payout.get("arrival_date"),
        }
    except stripe.error.StripeError as exc:
        log.error(f"Stripe error during payout: {exc}")
        return {"status": "error", "error": str(exc)}
    except Exception as exc:
        log.error(f"Unexpected error: {exc}")
        return {"status": "error", "error": str(exc)}


# ─────────────────────────────────────────────
# CLI / direct execution
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Garcar Withdrawal Agent")
    parser.add_argument("--force",   action="store_true", help="Bypass threshold, sweep now")
    parser.add_argument("--amount",  type=int, default=0, help="Specific amount in cents to sweep")
    parser.add_argument("--summary", action="store_true", help="Print ledger summary only")
    args = parser.parse_args()

    if args.summary:
        print_summary()
    else:
        result = run_withdrawal_sweep(force=args.force, override_amount_cents=args.amount)
        print(json.dumps(result, indent=2))
