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
APOLLO_KEY        = os.environ.get("APOLLO_API_KEY", "")
MIN_LEAD_SCORE    = float(os.environ.get("MIN_LEAD_SCORE", "60"))   # 0-100
LEADS_PER_CYCLE   = int(os.environ.get("LEADS_PER_CYCLE", "50"))
REV_PER_CLOSE     = float(os.environ.get("REVENUE_PER_CLOSE", "499"))  # default $499 deal
CONVERSION_RATE   = float(os.environ.get("ESTIMATED_CONVERSION_RATE", "0.05"))  # 5%
LEDGER_PATH       = os.environ.get("ACQ_LEDGER_PATH", "acquisition_ledger.json")

# DFW General Contractor targeting (primary niche)
DFW_CONTRACTOR_CONFIG = {
    "query": "general contractor construction DFW Dallas Fort Worth",
    "titles": [
        "Owner", "President", "CEO", "Principal",
        "General Contractor", "Project Manager", "VP Operations",
        "Director of Operations", "Founder"
    ],
    "employee_range": "1-100",
    "limit": LEADS_PER_CYCLE
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
    if not APOLLO_KEY:
        print("  ⚠️  APOLLO_API_KEY not set — skipping live scrape, using demo data.")
        return _demo_leads()
    apollo = ApolloLeadGen(APOLLO_KEY)
    leads = apollo.search_leads(
        query=config["query"],
        titles=config["titles"],
        employee_range=config["employee_range"],
        limit=config["limit"]
    )
    print(f"  ✅ Scraped {len(leads)} leads from Apollo.")
    return leads


# ── Stage 2: Score & Filter ───────────────────────────────────────────────────
def score_and_filter(leads: List[Dict], ledger: List[Dict]) -> List[Dict]:
    print(f"\n[STAGE 2] 📊 Scoring & filtering {len(leads)} leads...")
    scorer = LeadScorer()
    qualified = []
    for lead in leads:
        if already_contacted(lead.get("email", ""), ledger):
            continue
        try:
            score = scorer.score_lead(lead)
            lead["score"] = score
        except Exception:
            lead["score"] = 50  # default neutral score if scorer fails
        if lead["score"] >= MIN_LEAD_SCORE:
            qualified.append(lead)
    qualified.sort(key=lambda x: x["score"], reverse=True)
    print(f"  ✅ {len(qualified)} leads passed scoring threshold (>= {MIN_LEAD_SCORE}).")
    return qualified


# ── Stage 3: Outreach ─────────────────────────────────────────────────────────
def send_outreach(leads: List[Dict]) -> List[Dict]:
    print(f"\n[STAGE 3] 📧 Sending outreach emails...")
    sequencer = EmailNurtureSequencer()
    results = []
    for lead in leads:
        if not lead.get("email"):
            continue
        result = sequencer.trigger_welcome_sequence(lead, plan_name="Pro")
        record = {
            "email":        lead.get("email"),
            "name":         lead.get("name"),
            "company":      lead.get("company"),
            "score":        lead.get("score", 0),
            "contacted_at": datetime.utcnow().isoformat() + "Z",
            "email_status": "sent" if result.get("success") else "failed",
            "stage":        "outreach_sent",
            "source":       lead.get("source", "apollo"),
        }
        results.append(record)
        status = "✅" if result.get("success") else "❌"
        print(f"  {status} {lead.get('email')} (score: {lead.get('score', 0):.0f})")
        time.sleep(0.3)  # Rate limit courtesy
    print(f"  📬 Outreach sent to {sum(1 for r in results if r['email_status'] == 'sent')} leads.")
    return results


# ── Stage 4: Project Revenue & Feed ALW ───────────────────────────────────────
def project_and_allocate(cycle_results: List[Dict]) -> Dict:
    print(f"\n[STAGE 4] 💰 Projecting revenue & feeding ALW...")
    total_contacted   = len(cycle_results)
    projected_closes  = round(total_contacted * CONVERSION_RATE)
    projected_revenue = projected_closes * REV_PER_CLOSE

    print(f"  Leads contacted:      {total_contacted}")
    print(f"  Est. closes (5%):     {projected_closes}")
    print(f"  Projected revenue:    ${projected_revenue:,.2f}")

    if projected_revenue > 0:
        alw_dist = alw_run(
            gross_revenue=projected_revenue,
            source="customer_acquisition_loop",
            log=True
        )
    else:
        alw_dist = None
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
    print(f"\n{'='*60}")
    print(f"  🚀 GARCAR CUSTOMER ACQUISITION LOOP")
    print(f"  Timestamp: {ts}")
    print(f"  Niche:     {niche_config['query']}")
    print(f"{'='*60}")

    ledger = load_ledger()

    # Stage 1 — Scrape
    raw_leads = scrape_leads(niche_config)

    # Stage 2 — Score & Filter
    qualified = score_and_filter(raw_leads, ledger)

    if not qualified:
        print("\n⚠️  No qualified new leads this cycle. Exiting.")
        return {"status": "no_new_leads", "timestamp": ts}

    # Stage 3 — Outreach
    cycle_results = send_outreach(qualified)

    # Persist to ledger
    ledger.extend(cycle_results)
    save_ledger(ledger)

    # Stage 4 — Revenue Projection + ALW
    projection = project_and_allocate(cycle_results)

    summary = {
        "timestamp":          ts,
        "niche":              niche_config["query"],
        "raw_leads_scraped":  len(raw_leads),
        "qualified_leads":    len(qualified),
        **projection,
        "status": "complete"
    }

    print(f"\n{'='*60}")
    print(f"  ✅ CYCLE COMPLETE")
    print(f"  Scraped:   {summary['raw_leads_scraped']} | Qualified: {summary['qualified_leads']}")
    print(f"  Rev Est:   ${summary['projected_revenue']:,.2f}")
    print(f"  ALW Fed:   {'Yes' if summary['alw_triggered'] else 'No'}")
    print(f"{'='*60}\n")

    return summary


# ── Demo Data (no API key) ─────────────────────────────────────────────────────
def _demo_leads() -> List[Dict]:
    return [
        {"name": "John Hartwell",  "email": "j.hartwell@dfwbuilders.com",  "title": "Owner",    "company": "DFW Builders LLC",     "score": 0, "source": "demo"},
        {"name": "Maria Reyes",    "email": "m.reyes@texasgc.com",        "title": "President", "company": "Texas GC Group",       "score": 0, "source": "demo"},
        {"name": "Brandon Cole",   "email": "b.cole@coleconstruction.io", "title": "CEO",       "company": "Cole Construction",    "score": 0, "source": "demo"},
        {"name": "Sandra Wu",      "email": "s.wu@premierbuild.com",      "title": "VP Ops",    "company": "Premier Build Co",     "score": 0, "source": "demo"},
        {"name": "Travis Monroe",  "email": "t.monroe@monroegc.com",     "title": "Founder",   "company": "Monroe General Contracting", "score": 0, "source": "demo"},
    ]


if __name__ == "__main__":
    import sys
    niche = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    config = DFW_CONTRACTOR_CONFIG if not niche else {**DFW_CONTRACTOR_CONFIG, "query": niche}
    run_acquisition_loop(config)
