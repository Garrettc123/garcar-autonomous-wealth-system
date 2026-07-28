# customer_acquisition_loop.py — Garcar Enterprise Customer Acquisition Loop
# Full autonomous cycle: Scrape → Score → Outreach → Nurture → Convert → ALW Allocation
# Runs via GitHub Actions on schedule or manual trigger.

import os
import json
import time
from datetime import datetime
from typing import List, Dict

from lead_acquisition import ApolloLeadGen
from lead_scoring import LeadScorer
from email_nurture import EmailNurtureSequencer
from abundance_wallet import run as alw_run

# ── Config ────────────────────────────────────────────────────────────────────
APOLLO_KEY       = os.environ.get("APOLLO_API_KEY", "")
MIN_LEAD_SCORE   = float(os.environ.get("MIN_LEAD_SCORE", "60"))
LEADS_PER_CYCLE  = int(os.environ.get("LEADS_PER_CYCLE", "50"))
REV_PER_CLOSE    = float(os.environ.get("REVENUE_PER_CLOSE", "499"))
CONVERSION_RATE  = float(os.environ.get("ESTIMATED_CONVERSION_RATE", "0.05"))
LEDGER_PATH      = os.environ.get("ACQ_LEDGER_PATH", "acquisition_ledger.json")
DRY_RUN          = os.environ.get("DRY_RUN", "false").lower() == "true"  # FIXED: now respected

# DFW General Contractor targeting (primary niche)
DFW_CONTRACTOR_CONFIG = {
    "query":          "general contractor construction DFW Dallas Fort Worth",
    "titles":         [
        "Owner", "President", "CEO", "Principal",
        "General Contractor", "Project Manager", "VP Operations",
        "Director of Operations", "Founder",
    ],
    "employee_range": "1-100",
    "limit":          LEADS_PER_CYCLE,
}


# ── Loop State ────────────────────────────────────────────────────────────────
def load_ledger() -> List[Dict]:
    try:
        with open(LEDGER_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_ledger(ledger: List[Dict]) -> None:
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)

def already_contacted(email: str, ledger: List[Dict]) -> bool:
    return any(r.get("email") == email for r in ledger)


# ── Stage 1: Lead Scrape ──────────────────────────────────────────────────────
def scrape_leads(config: Dict = DFW_CONTRACTOR_CONFIG) -> List[Dict]:
    print(f"\n[STAGE 1] 🔍 Scraping leads via Apollo...")
    if DRY_RUN:
        print("  [DRY RUN] Using demo leads instead of live Apollo call.")
        return _demo_leads()
    if not APOLLO_KEY:
        print("  ⚠️  APOLLO_API_KEY not set — falling back to demo data.")
        return _demo_leads()
    apollo = ApolloLeadGen(APOLLO_KEY)
    leads  = apollo.search_leads(
        query=config["query"],
        titles=config["titles"],
        employee_range=config["employee_range"],
        limit=config["limit"],
    )
    print(f"  ✅ Scraped {len(leads)} leads from Apollo.")
    return leads


# ── Stage 2: Score & Filter ───────────────────────────────────────────────────
def score_and_filter(leads: List[Dict], ledger: List[Dict]) -> List[Dict]:
    print(f"\n[STAGE 2] 📊 Scoring & filtering {len(leads)} leads...")
    scorer    = LeadScorer()
    qualified = []
    for lead in leads:
        if already_contacted(lead.get("email", ""), ledger):
            continue
        try:
            score = scorer.score_lead(lead)
        except Exception:
            score = 50  # neutral fallback
        lead["score"] = score
        if score >= MIN_LEAD_SCORE:
            qualified.append(lead)
    qualified.sort(key=lambda x: x["score"], reverse=True)
    print(f"  ✅ {len(qualified)} leads passed threshold (>= {MIN_LEAD_SCORE}).")
    return qualified


# ── Stage 3: Outreach ─────────────────────────────────────────────────────────
def send_outreach(leads: List[Dict]) -> List[Dict]:
    print(f"\n[STAGE 3] 📧 {'[DRY RUN] ' if DRY_RUN else ''}Sending outreach emails...")
    sequencer = EmailNurtureSequencer()
    results   = []
    for lead in leads:
        if not lead.get("email"):
            continue
        result = sequencer.trigger_welcome_sequence(lead, plan_name="Pro")
        record = {
            "email":        lead.get("email"),
            "name":         lead.get("name"),
            "company":      lead.get("company"),
            "phone":        lead.get("phone"),
            "score":        lead.get("score", 0),
            "contacted_at": datetime.utcnow().isoformat() + "Z",
            "email_status": "sent" if result.get("success") else "failed",
            "dry_run":      result.get("dry_run", False),
            "stage":        "outreach_sent",
            "source":       lead.get("source", "apollo"),
        }
        results.append(record)
        icon = "🧪" if record["dry_run"] else ("✅" if record["email_status"] == "sent" else "❌")
        print(f"  {icon} {lead.get('email')} (score: {lead.get('score', 0):.0f})")
        time.sleep(0.3)
    sent = sum(1 for r in results if r["email_status"] == "sent" and not r.get("dry_run"))
    print(f"  📬 Outreach sent to {sent} leads.")
    return results


# ── Stage 4: Project Revenue & Feed ALW ───────────────────────────────────────
def project_and_allocate(cycle_results: List[Dict]) -> Dict:
    print(f"\n[STAGE 4] 💰 Projecting revenue & feeding ALW...")
    total_contacted   = len(cycle_results)
    projected_closes  = round(total_contacted * CONVERSION_RATE)
    projected_revenue = projected_closes * REV_PER_CLOSE

    print(f"  Leads contacted:   {total_contacted}")
    print(f"  Est. closes (5%):  {projected_closes}")
    print(f"  Projected revenue: ${projected_revenue:,.2f}")

    alw_dist = None
    if projected_revenue > 0 and not DRY_RUN:
        alw_dist = alw_run(
            gross_revenue=projected_revenue,
            source="customer_acquisition_loop",
            log=True,
        )
    elif DRY_RUN:
        print("  [DRY RUN] ALW allocation skipped.")
    else:
        print("  ⚠️  No projected revenue this cycle — ALW not triggered.")

    return {
        "total_contacted":   total_contacted,
        "projected_closes":  projected_closes,
        "projected_revenue": projected_revenue,
        "alw_triggered":     alw_dist is not None,
    }


# ── Master Loop ───────────────────────────────────────────────────────────────
def run_acquisition_loop(niche_config: Dict = DFW_CONTRACTOR_CONFIG) -> Dict:
    ts = datetime.utcnow().isoformat() + "Z"
    mode = "[DRY RUN] " if DRY_RUN else ""
    print(f"\n{'='*60}")
    print(f"  🚀 {mode}GARCAR CUSTOMER ACQUISITION LOOP")
    print(f"  Timestamp: {ts}")
    print(f"  Niche:     {niche_config['query']}")
    print(f"{'='*60}")

    ledger    = load_ledger()
    raw_leads = scrape_leads(niche_config)
    qualified = score_and_filter(raw_leads, ledger)

    if not qualified:
        print("\n⚠️  No qualified new leads this cycle. Exiting.")
        return {"status": "no_new_leads", "timestamp": ts}

    cycle_results = send_outreach(qualified)
    ledger.extend(cycle_results)
    save_ledger(ledger)
    projection = project_and_allocate(cycle_results)

    summary = {
        "timestamp":         ts,
        "niche":             niche_config["query"],
        "dry_run":           DRY_RUN,
        "raw_leads_scraped": len(raw_leads),
        "qualified_leads":   len(qualified),
        **projection,
        "status": "complete",
    }

    print(f"\n{'='*60}")
    print(f"  ✅ {mode}CYCLE COMPLETE")
    print(f"  Scraped:   {summary['raw_leads_scraped']} | Qualified: {summary['qualified_leads']}")
    print(f"  Rev Est:   ${summary['projected_revenue']:,.2f}")
    print(f"  ALW Fed:   {'Yes' if summary['alw_triggered'] else 'No'}")

    # ── Hot Leads (score ≥ 80) ────────────────────────────────────────
    hot_leads = [r for r in cycle_results if float(r.get('score', 0)) >= 80]
    verbose = os.environ.get("VERBOSE_LEADS", "false").lower() == "true"
    print(f"\n  🔥 HOT LEADS ({len(hot_leads)} contacts, score ≥ 80):")
    if hot_leads:
        for lead in hot_leads:
            if verbose:
                print(f"    🎯 {lead.get('name')} | {lead.get('company')} | Score: {lead.get('score')} | {lead.get('email')}")
            else:
                print(f"    🎯 {lead.get('company')} | Score: {lead.get('score')}")
    else:
        print("    None this cycle — try lowering MIN_LEAD_SCORE or broadening niche.")

    print(f"{'='*60}\n")
    return summary


# ── Demo Data (no API key / dry run) ──────────────────────────────────────────
def _demo_leads() -> List[Dict]:
    return [
        {"name": "John Hartwell",  "email": "j.hartwell@dfwbuilders.com",  "title": "Owner",    "company": "DFW Builders LLC",          "score": 0, "source": "demo"},
        {"name": "Maria Reyes",    "email": "m.reyes@texasgc.com",         "title": "President", "company": "Texas GC Group",           "score": 0, "source": "demo"},
        {"name": "Brandon Cole",   "email": "b.cole@coleconstruction.io",  "title": "CEO",       "company": "Cole Construction",         "score": 0, "source": "demo"},
        {"name": "Sandra Wu",      "email": "s.wu@premierbuild.com",       "title": "VP Ops",    "company": "Premier Build Co",          "score": 0, "source": "demo"},
        {"name": "Travis Monroe",  "email": "t.monroe@monroegc.com",      "title": "Founder",   "company": "Monroe General Contracting", "score": 0, "source": "demo"},
    ]


if __name__ == "__main__":
    import sys
    niche  = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    config = DFW_CONTRACTOR_CONFIG if not niche else {**DFW_CONTRACTOR_CONFIG, "query": niche}
    run_acquisition_loop(config)
