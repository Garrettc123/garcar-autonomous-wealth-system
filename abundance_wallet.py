# abundance_wallet.py — Garcar Enterprise Abundance Living Wallet (ALW)
# Auto-allocates 18% of gross revenue into sub-buckets for abundant living.
# Fires on every Stripe/PayPal webhook event via GitHub Actions or dashboard_api.py

import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

# ── Core Allocation Constants ───────────────────────────────────────────────
ALW_PERCENTAGE = 0.18  # 18% of gross revenue → Abundance Living Wallet

SUB_BUCKETS = {
    "home":           0.30,   # Mortgage/rent, upgrades, comfort
    "family":         0.25,   # Hannah + kids, activities, needs
    "food_dining":    0.12,   # Quality meals, not survival eating
    "transportation": 0.10,   # Vehicle, fuel, maintenance
    "church_giving":  0.10,   # Tithe + charitable giving
    "personal":       0.08,   # Clothing, health, grooming
    "experiences":    0.05,   # Travel, dates, family trips
}

LEDGER_PATH = os.getenv("ALW_LEDGER_PATH", "alw_ledger.json")


@dataclass
class ALWDistribution:
    timestamp: str
    gross_revenue: float
    alw_total: float
    buckets: dict
    source: str
    status: str = "allocated"


def allocate(gross_revenue: float, source: str = "manual") -> ALWDistribution:
    """Compute ALW split from gross revenue."""
    alw_total = round(gross_revenue * ALW_PERCENTAGE, 2)
    buckets = {
        name: round(alw_total * pct, 2)
        for name, pct in SUB_BUCKETS.items()
    }
    return ALWDistribution(
        timestamp=datetime.utcnow().isoformat() + "Z",
        gross_revenue=gross_revenue,
        alw_total=alw_total,
        buckets=buckets,
        source=source,
    )


def log_distribution(dist: ALWDistribution, path: str = LEDGER_PATH) -> None:
    """Append allocation record to the JSON ledger."""
    try:
        with open(path, "r") as f:
            ledger = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        ledger = []
    ledger.append(asdict(dist))
    with open(path, "w") as f:
        json.dump(ledger, f, indent=2)


def print_report(dist: ALWDistribution) -> None:
    """Human-readable ALW summary."""
    print(f"\n{'='*52}")
    print(f"  💰 ABUNDANCE LIVING WALLET  —  {dist.timestamp[:10]}")
    print(f"{'='*52}")
    print(f"  Source:          {dist.source}")
    print(f"  Gross Revenue:   ${dist.gross_revenue:>12,.2f}")
    print(f"  ALW Total (18%): ${dist.alw_total:>12,.2f}")
    print(f"  {'─'*44}")
    for bucket, amount in dist.buckets.items():
        label = bucket.replace("_", " ").title()
        print(f"  {label:<22}  ${amount:>10,.2f}")
    print(f"{'='*52}\n")


def run(gross_revenue: float, source: str = "manual", log: bool = True) -> ALWDistribution:
    """Main entry point: allocate, log, and report."""
    dist = allocate(gross_revenue, source)
    if log:
        log_distribution(dist)
    print_report(dist)
    return dist


# ── CLI / Direct Execution ───────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    revenue = float(sys.argv[1]) if len(sys.argv) > 1 else 10890.00
    src = sys.argv[2] if len(sys.argv) > 2 else "cli"
    run(gross_revenue=revenue, source=src)
