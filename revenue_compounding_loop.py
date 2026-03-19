"""GARCAR REVENUE COMPOUNDING LOOP

Takes every Stripe payment event and multiplies it:
  1. Upsell trigger   → send upgrade email to new customers within 24h
  2. Referral trigger → send referral invite to customers who paid >$500
  3. Affiliate payout → auto-pay affiliate if conversion tracked
  4. RLHF signal      → feed successful conversion data to rlhf_agent
  5. Linear task      → auto-create follow-up task for high-value accounts

Every dollar earned seeds 5 additional revenue attempts.
"""

import os
import json
import boto3
import importlib
from datetime import datetime, timezone
from typing import List, Dict

REGION  = os.environ.get('AWS_REGION', 'us-east-1')
BUCKET  = os.environ.get('S3_BUCKET', 'garcar-revenue-data')

def _mod(name):
    try: return importlib.import_module(name)
    except: return None

email_nurture  = _mod('email_nurture')
affiliate      = _mod('affiliate_system')
rlhf           = _mod('rlhf_agent')
linear         = _mod('linear_integration')


class RevenueCompoundingLoop:
    def __init__(self):
        self.s3  = boto3.client('s3',  region_name=REGION)
        self.ssm = boto3.client('ssm', region_name=REGION)
        self.ses = boto3.client('ses', region_name=REGION)
        self.multiplied = 0

    def _ssm(self, key: str, default='') -> str:
        try:
            r = self.ssm.get_parameter(Name=f'/garcar/{key}', WithDecryption=True)
            return r['Parameter']['Value']
        except:
            return os.environ.get(key, default)

    def load_recent_payments(self) -> List[Dict]:
        """Load unprocessed Stripe payment events from S3."""
        try:
            r = self.s3.list_objects_v2(Bucket=BUCKET, Prefix='payments/unprocessed/')
            events = []
            for obj in r.get('Contents', [])[:50]:
                data = self.s3.get_object(Bucket=BUCKET, Key=obj['Key'])
                events.append({
                    'key': obj['Key'],
                    'event': json.loads(data['Body'].read())
                })
            return events
        except Exception as e:
            print(f'  [compounding] load payments: {e}')
            return []

    def mark_processed(self, key: str):
        try:
            # Move to processed/
            copy_src = {'Bucket': BUCKET, 'Key': key}
            new_key  = key.replace('unprocessed/', 'processed/')
            self.s3.copy_object(Bucket=BUCKET, Key=new_key, CopySource=copy_src)
            self.s3.delete_object(Bucket=BUCKET, Key=key)
        except: pass

    def trigger_upsell(self, customer_email: str, amount: int):
        """Send upsell email within 24h of first payment."""
        upgrade_url = self._ssm('UPGRADE_URL', 'https://app.garcar.io/upgrade')
        sender      = self._ssm('SES_SENDER_EMAIL', 'noreply@garcar.io')
        try:
            self.ses.send_email(
                Source=sender,
                Destination={'ToAddresses': [customer_email]},
                Message={
                    'Subject': {'Data': 'Unlock the full Garcar system'},
                    'Body': {'Html': {'Data': f"""
                        <p>Thanks for joining Garcar!</p>
                        <p>Customers who upgrade to Pro see 3x faster results.</p>
                        <p><a href="{upgrade_url}">Upgrade now →</a></p>
                    """}}
                }
            )
            print(f'    ✅ Upsell sent to {customer_email}')
            self.multiplied += 1
        except Exception as e:
            print(f'    Upsell error: {e}')

    def trigger_referral(self, customer_email: str):
        """Invite high-value customers to refer others."""
        cal_url = self._ssm('CALENDAR_URL', 'https://cal.garcar.io/enterprise')
        sender  = self._ssm('SES_SENDER_EMAIL', 'noreply@garcar.io')
        try:
            self.ses.send_email(
                Source=sender,
                Destination={'ToAddresses': [customer_email]},
                Message={
                    'Subject': {'Data': 'Earn $200 per referral — Garcar Partner Program'},
                    'Body': {'Html': {'Data': f"""
                        <p>You're one of our top customers!</p>
                        <p>Refer a colleague and earn $200 for each signup.</p>
                        <p><a href="{cal_url}">Book a partner call →</a></p>
                    """}}
                }
            )
            print(f'    ✅ Referral invite sent to {customer_email}')
            self.multiplied += 1
        except Exception as e:
            print(f'    Referral error: {e}')

    def feed_rlhf(self, event: Dict):
        """Send successful conversion signal to RLHF agent for self-improvement."""
        if rlhf and hasattr(rlhf, 'record_success'):
            try:
                rlhf.record_success(event)
                print(f'    ✅ RLHF conversion signal recorded')
                self.multiplied += 1
            except Exception as e:
                print(f'    RLHF signal: {e}')

    def create_linear_task(self, customer_email: str, amount: int):
        """Auto-create high-value follow-up task in Linear."""
        if linear and hasattr(linear, 'create_task'):
            try:
                linear.create_task(
                    title=f'High-value follow-up: {customer_email} (${amount/100:.0f})',
                    description=f'Paid ${amount/100:.0f}. Schedule enterprise upsell call.',
                    priority='urgent'
                )
                print(f'    ✅ Linear task created for {customer_email}')
                self.multiplied += 1
            except Exception as e:
                print(f'    Linear task: {e}')

    def process_event(self, key: str, event: Dict):
        obj_type = event.get('type', '')
        data     = event.get('data', {}).get('object', {})
        email    = data.get('customer_email') or data.get('receipt_email', '')
        amount   = data.get('amount', 0)

        if obj_type in ('payment_intent.succeeded', 'checkout.session.completed',
                        'invoice.payment_succeeded'):
            print(f'  Processing: {obj_type} | {email} | ${amount/100:.2f}')
            if email:
                self.trigger_upsell(email, amount)
                if amount >= 50000:  # $500+
                    self.trigger_referral(email)
                    self.create_linear_task(email, amount)
            self.feed_rlhf(event)
            self.mark_processed(key)

    def run(self):
        print('\n[Revenue Compounding Loop]')
        events = self.load_recent_payments()
        if not events:
            print('  No unprocessed payment events.')
            return {'multiplied': 0}
        for item in events:
            self.process_event(item['key'], item['event'])
        print(f'  Multiplied {self.multiplied} additional revenue actions from {len(events)} events.')
        return {'multiplied': self.multiplied, 'events_processed': len(events)}


if __name__ == '__main__':
    RevenueCompoundingLoop().run()
