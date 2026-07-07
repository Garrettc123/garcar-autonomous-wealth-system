"""GARCAR MASTER ORCHESTRATOR — Wires Every Source File Into One Autonomous Loop

Connects:
  lead_acquisition.py       → Apollo lead scraping
  lead_scoring.py           → ML score filter
  customer_acquisition_loop.py → full nurture cycle
  email_nurture.py          → SES drip sequences
  sms_outreach.py           → Twilio SMS cadence
  affiliate_system.py       → Affiliate tracking
  stripe_webhook.py         → Payment events
  revenue_agent.js          → JS revenue logic (subprocess)
  agent_coordinator.py      → Multi-agent orchestration
  rlhf_agent.py             → Self-improving AI
  abundance_wallet.py       → Wealth allocation
  dashboard_api.py          → Metrics/reporting
  quantum_crypto.py         → Encryption layer
  linear_integration.py     → Issue/task tracking
  aws_utils.py              → S3/SSM helpers
  secrets_manager.py        → Secrets resolution
  secrets_provisioner.py    → Self-healing key sync

Outputs every cycle:
  - Leads scraped, scored, queued
  - Emails + SMS dispatched
  - Stripe revenue events processed
  - Affiliate payouts triggered
  - Wealth allocation updated
  - RLHF self-improvement loop
  - Linear tasks auto-closed
  - Dashboard metrics pushed to S3
"""

import os
import sys
import json
import time
import subprocess
import importlib
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, List

import requests

from core.event_bus import build_event, integration_event_bus
from secrets_manager import get as get_secret

# ── Load all secrets from SSM before anything else ──────────────────────────
try:
    from secrets_provisioner import SecretsProvisioner
    _prov = SecretsProvisioner()
    _prov.load_from_ssm()
    print("[orchestrator] Secrets loaded from SSM")
except Exception as e:
    print(f"[orchestrator] SSM load warning: {e} — falling back to env vars")

# ── Import every source module ───────────────────────────────────────────────
def safe_import(module_name: str):
    try:
        return importlib.import_module(module_name.replace('.py', ''))
    except Exception as e:
        print(f"  [import] {module_name}: {e}")
        return None

MODULES = {
    'lead_acquisition':         safe_import('lead_acquisition'),
    'lead_scoring':             safe_import('lead_scoring'),
    'customer_acquisition_loop':safe_import('customer_acquisition_loop'),
    'email_nurture':            safe_import('email_nurture'),
    'sms_outreach':             safe_import('sms_outreach'),
    'affiliate_system':         safe_import('affiliate_system'),
    'stripe_webhook':           safe_import('stripe_webhook'),
    'agent_coordinator':        safe_import('agent_coordinator'),
    'rlhf_agent':               safe_import('rlhf_agent'),
    'abundance_wallet':         safe_import('abundance_wallet'),
    'dashboard_api':            safe_import('dashboard_api'),
    'linear_integration':       safe_import('linear_integration'),
    'aws_utils':                safe_import('aws_utils'),
    'secrets_manager':          safe_import('secrets_manager'),
    'quantum_crypto':           safe_import('quantum_crypto'),
}

loaded = [k for k, v in MODULES.items() if v is not None]
print(f"[orchestrator] Loaded {len(loaded)}/{len(MODULES)} modules: {', '.join(loaded)}")


class MasterOrchestrator:
    def __init__(self):
        self.cycle       = 0
        self.metrics     = self._init_metrics()
        self.start_time  = datetime.now(timezone.utc)

    def _init_metrics(self) -> Dict[str, Any]:
        return {
            'leads_scraped':      0,
            'leads_qualified':    0,
            'emails_sent':        0,
            'sms_sent':           0,
            'revenue_events':     0,
            'fulfillment_dispatches': 0,
            'affiliates_paid':    0,
            'rlhf_improvements':  0,
            'errors':             [],
            'cycles_completed':   0,
        }

    def _run(self, label: str, fn):
        """Safe wrapper — logs, times, catches."""
        t = time.time()
        try:
            result = fn()
            elapsed = round(time.time() - t, 2)
            print(f"  ✅ {label} ({elapsed}s)")
            return result
        except Exception as e:
            elapsed = round(time.time() - t, 2)
            print(f"  ❌ {label} ({elapsed}s): {e}")
            self.metrics['errors'].append({'step': label, 'error': str(e),
                                           'ts': datetime.now(timezone.utc).isoformat()})
            return None

    # ── 1. Lead Pipeline ─────────────────────────────────────────────────────
    def run_lead_pipeline(self):
        print("\n[1/8] Lead Pipeline")
        la = MODULES.get('lead_acquisition')
        ls = MODULES.get('lead_scoring')
        cal = MODULES.get('customer_acquisition_loop')

        leads = []
        if la and hasattr(la, 'fetch_leads'):
            leads = self._run('fetch_leads', la.fetch_leads) or []
            self.metrics['leads_scraped'] += len(leads)
        elif la and hasattr(la, 'run'):
            leads = self._run('lead_acquisition.run', la.run) or []
            self.metrics['leads_scraped'] += len(leads) if isinstance(leads, list) else 1

        qualified = leads
        if ls and leads:
            if hasattr(ls, 'score_and_filter'):
                qualified = self._run('score_leads', lambda: ls.score_and_filter(leads)) or []
            elif hasattr(ls, 'run'):
                qualified = self._run('lead_scoring.run', ls.run) or leads
            self.metrics['leads_qualified'] += len(qualified) if isinstance(qualified, list) else 0

        if cal and hasattr(cal, 'process_leads') and qualified:
            self._run('customer_acquisition_loop', lambda: cal.process_leads(qualified))
        elif cal and hasattr(cal, 'run'):
            self._run('customer_acquisition_loop.run', cal.run)

        return qualified

    # ── 2. Multi-Channel Outreach ────────────────────────────────────────────
    def run_outreach(self, leads=None):
        print("\n[2/8] Multi-Channel Outreach (Email + SMS)")
        en = MODULES.get('email_nurture')
        sms = MODULES.get('sms_outreach')

        if en:
            if hasattr(en, 'run_sequences'):
                r = self._run('email_nurture.run_sequences', en.run_sequences)
            elif hasattr(en, 'run'):
                r = self._run('email_nurture.run', en.run)
            else:
                r = None
            if r and isinstance(r, dict):
                self.metrics['emails_sent'] += r.get('sent', 0)

        if sms:
            if hasattr(sms, 'run_outreach'):
                r = self._run('sms_outreach.run_outreach', sms.run_outreach)
            elif hasattr(sms, 'run'):
                r = self._run('sms_outreach.run', sms.run)
            else:
                r = None
            if r and isinstance(r, dict):
                self.metrics['sms_sent'] += r.get('sent', 0)

    # ── 3. Revenue Events ────────────────────────────────────────────────────
    def run_revenue_processing(self):
        print("\n[3/8] Revenue Processing")
        sw = MODULES.get('stripe_webhook')
        aff = MODULES.get('affiliate_system')

        if sw:
            if hasattr(sw, 'process_pending'):
                r = self._run('stripe_webhook.process_pending', sw.process_pending)
            elif hasattr(sw, 'run'):
                r = self._run('stripe_webhook.run', sw.run)
            if r and isinstance(r, dict):
                self.metrics['revenue_events'] += r.get('processed', 0)

        if aff:
            if hasattr(aff, 'process_commissions'):
                r = self._run('affiliate.process_commissions', aff.process_commissions)
            elif hasattr(aff, 'run'):
                r = self._run('affiliate_system.run', aff.run)
            if r and isinstance(r, dict):
                self.metrics['affiliates_paid'] += r.get('paid', 0)

        # Also invoke revenue_agent.js via subprocess
        self._run('revenue_agent.js', lambda: subprocess.run(
            ['node', 'revenue_agent.js', '--mode=process'],
            capture_output=True, timeout=60
        ))

    def run_fulfillment(self):
        print("\n[3b/8] Fulfillment Dispatch")
        fulfillment_url = (get_secret('FULFILLMENT_WEBHOOK_URL') or '').strip()
        fulfillment_secret = (get_secret('FULFILLMENT_WEBHOOK_SECRET') or '').strip()
        batch_size = int(os.environ.get('GARCAR_FULFILLMENT_BATCH_SIZE', '25'))
        timeout = float(os.environ.get('FULFILLMENT_WEBHOOK_TIMEOUT', '10'))
        if not fulfillment_url:
            print("  ⚠️  FULFILLMENT_WEBHOOK_URL not configured — skipping")
            return

        payment_events = integration_event_bus.read_events_sync(
            event_type='payment.confirmed',
            count=batch_size,
        )
        dispatched = 0

        for event in payment_events:
            event_id = event.get('event_id')
            if not event_id or integration_event_bus.is_dispatched_sync(event_id):
                continue

            try:
                response = requests.post(
                    fulfillment_url,
                    json={"trigger": "payment.confirmed", "event": event},
                    headers={
                        "Content-Type": "application/json",
                        **(
                            {"X-Garcar-Webhook-Secret": fulfillment_secret}
                            if fulfillment_secret else {}
                        ),
                    },
                    timeout=timeout,
                )
                response.raise_for_status()

                integration_event_bus.mark_dispatched_sync(
                    event_id,
                    dispatcher='fulfillment',
                    result={"status_code": response.status_code},
                )
                integration_event_bus.publish_sync(
                    build_event(
                        "fulfillment.started",
                        {
                            "upstream_event_id": event_id,
                            "fulfillment_url": fulfillment_url,
                            "status_code": response.status_code,
                        },
                        source="garcar-autonomous-wealth-system/orchestrator",
                        entity_type="fulfillment",
                        entity_id=event.get('entity_id') or event_id,
                        correlation_id=event_id,
                        metadata={"dispatcher": "fulfillment"},
                        status="dispatched",
                    )
                )
                dispatched += 1
            except Exception as exc:
                print(f"  ❌ Fulfillment dispatch failed for {event_id}: {exc}")
                self.metrics['errors'].append({
                    'step': 'fulfillment_dispatch',
                    'event_id': event_id,
                    'error': str(exc),
                    'ts': datetime.now(timezone.utc).isoformat(),
                })

        self.metrics['fulfillment_dispatches'] += dispatched
        print(f"  ✅ Fulfillment dispatched: {dispatched}")

    # ── 4. AI Agent Coordination ─────────────────────────────────────────────
    def run_agents(self):
        print("\n[4/8] AI Agent Coordination")
        ac = MODULES.get('agent_coordinator')
        rlhf = MODULES.get('rlhf_agent')

        if ac:
            if hasattr(ac, 'run_all_agents'):
                self._run('agent_coordinator.run_all_agents', ac.run_all_agents)
            elif hasattr(ac, 'run'):
                self._run('agent_coordinator.run', ac.run)

        if rlhf:
            if hasattr(rlhf, 'improve'):
                r = self._run('rlhf_agent.improve', rlhf.improve)
            elif hasattr(rlhf, 'run'):
                r = self._run('rlhf_agent.run', rlhf.run)
            else:
                r = None
            if r and isinstance(r, dict):
                self.metrics['rlhf_improvements'] += r.get('improvements', 0)

    # ── 5. Wealth Allocation ─────────────────────────────────────────────────
    def run_wealth_allocation(self):
        print("\n[5/8] Wealth Allocation")
        aw = MODULES.get('abundance_wallet')
        if aw:
            if hasattr(aw, 'allocate'):
                self._run('abundance_wallet.allocate', aw.allocate)
            elif hasattr(aw, 'run'):
                self._run('abundance_wallet.run', aw.run)

    # ── 6. Linear Task Automation ────────────────────────────────────────────
    def run_linear_sync(self):
        print("\n[6/8] Linear Task Sync")
        li = MODULES.get('linear_integration')
        if li:
            if hasattr(li, 'auto_close_completed'):
                self._run('linear.auto_close', li.auto_close_completed)
            elif hasattr(li, 'run'):
                self._run('linear_integration.run', li.run)

    # ── 7. Secrets Self-Heal ─────────────────────────────────────────────────
    def run_secrets_heal(self):
        print("\n[7/8] Secrets Self-Heal")
        try:
            from secrets_provisioner import SecretsProvisioner
            sp = SecretsProvisioner()
            sp.load_from_ssm()
            sp.sync_to_github()
            print("  ✅ Secrets synced to GitHub Actions")
        except Exception as e:
            print(f"  ⚠️  Secrets heal: {e}")

    # ── 8. Dashboard Push ────────────────────────────────────────────────────
    def run_dashboard_push(self):
        print("\n[8/8] Dashboard Metrics Push")
        da = MODULES.get('dashboard_api')
        au = MODULES.get('aws_utils')

        self.metrics['cycles_completed'] = self.cycle
        self.metrics['uptime_seconds'] = round(
            (datetime.now(timezone.utc) - self.start_time).total_seconds()
        )
        self.metrics['timestamp'] = datetime.now(timezone.utc).isoformat()

        if da:
            if hasattr(da, 'push_metrics'):
                self._run('dashboard.push_metrics',
                          lambda: da.push_metrics(self.metrics))
            elif hasattr(da, 'run'):
                self._run('dashboard_api.run', da.run)

        # Always push metrics JSON to S3
        if au and hasattr(au, 'upload_json'):
            self._run('s3.metrics_push',
                      lambda: au.upload_json('garcar-revenue-data',
                                             f'metrics/cycle_{self.cycle}.json',
                                             self.metrics))
        else:
            try:
                import boto3
                s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION','us-east-1'))
                s3.put_object(
                    Bucket='garcar-revenue-data',
                    Key=f'metrics/cycle_{self.cycle}.json',
                    Body=json.dumps(self.metrics, indent=2),
                    ContentType='application/json'
                )
                print("  ✅ Metrics pushed to S3")
            except Exception as e:
                print(f"  ⚠️  S3 push: {e}")

    # ── Master Run ───────────────────────────────────────────────────────────
    def run_cycle(self):
        self.cycle += 1
        print("\n" + "="*64)
        print(f"  GARCAR MASTER CYCLE #{self.cycle}")
        print(f"  {datetime.now(timezone.utc).isoformat()}Z")
        print("="*64)

        leads = self.run_lead_pipeline()
        self.run_outreach(leads)
        self.run_revenue_processing()
        self._run('fulfillment_dispatch', self.run_fulfillment)
        self.run_agents()
        self.run_wealth_allocation()
        self.run_linear_sync()
        self.run_secrets_heal()
        self.run_dashboard_push()

        print("\n" + "─"*64)
        print(f"  Cycle #{self.cycle} complete")
        print(f"  Leads:    {self.metrics['leads_scraped']} scraped / {self.metrics['leads_qualified']} qualified")
        print(f"  Outreach: {self.metrics['emails_sent']} emails / {self.metrics['sms_sent']} SMS")
        revenue_summary = (
            f"  Revenue:  {self.metrics['revenue_events']} events / "
            f"{self.metrics['fulfillment_dispatches']} fulfillment dispatches / "
            f"{self.metrics['affiliates_paid']} affiliate payouts"
        )
        print(revenue_summary)
        print(f"  Errors:   {len(self.metrics['errors'])}")
        print("─"*64 + "\n")
        return self.metrics


if __name__ == '__main__':
    orch = MasterOrchestrator()
    orch.run_cycle()
