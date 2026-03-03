"""Affiliate Referral System Tracking
Tracks affiliate referrals, commissions, and payouts for Garcar growth program
"""
import os
import json
import uuid
import boto3
from datetime import datetime
from typing import Dict, List, Optional

s3 = boto3.client('s3')
S3_BUCKET = os.environ.get('S3_BUCKET', 'garcar-revenue-data')
AFFILIATE_KEY_PREFIX = 'affiliates/'

# Commission rates per plan tier
COMMISSION_RATES = {
    'basic': 0.20,       # 20% of $49 = $9.80
    'pro': 0.25,         # 25% of $99 = $24.75
    'enterprise': 0.30   # 30% of $299 = $89.70
}

PLAN_PRICES = {
    'basic': 49,
    'pro': 99,
    'enterprise': 299
}


def _generate_referral_code(affiliate_id: str) -> str:
    """Generate a unique referral code for an affiliate"""
    short = affiliate_id[:8].upper()
    suffix = uuid.uuid4().hex[:4].upper()
    return f"GAR-{short}-{suffix}"


class AffiliateSystem:
    """Tracks affiliates, referrals, and commission payouts stored in S3."""

    def _load_affiliate(self, affiliate_id: str) -> Optional[Dict]:
        """Load affiliate record from S3"""
        try:
            obj = s3.get_object(
                Bucket=S3_BUCKET,
                Key=f"{AFFILIATE_KEY_PREFIX}{affiliate_id}.json"
            )
            return json.loads(obj['Body'].read())
        except s3.exceptions.NoSuchKey:
            return None
        except Exception as e:
            print(f"Error loading affiliate {affiliate_id}: {e}")
            return None

    def _save_affiliate(self, affiliate: Dict) -> bool:
        """Persist affiliate record to S3"""
        try:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=f"{AFFILIATE_KEY_PREFIX}{affiliate['id']}.json",
                Body=json.dumps(affiliate, indent=2),
                ContentType='application/json'
            )
            return True
        except Exception as e:
            print(f"Error saving affiliate {affiliate.get('id')}: {e}")
            return False

    def register_affiliate(self, name: str, email: str, payment_email: str = None) -> Dict:
        """Register a new affiliate partner"""
        affiliate_id = str(uuid.uuid4())
        affiliate = {
            'id': affiliate_id,
            'name': name,
            'email': email,
            'payment_email': payment_email or email,
            'referral_code': _generate_referral_code(affiliate_id),
            'status': 'active',
            'total_referrals': 0,
            'total_conversions': 0,
            'total_commission_earned': 0.0,
            'total_commission_paid': 0.0,
            'referrals': [],
            'created_at': datetime.utcnow().isoformat()
        }
        self._save_affiliate(affiliate)
        print(f"✅ Registered affiliate: {name} ({affiliate['referral_code']})")
        return affiliate

    def track_referral(self, referral_code: str, lead_email: str,
                       lead_name: str = None, source: str = 'web') -> Dict:
        """Record a new referral from an affiliate link"""
        affiliate = self._find_by_code(referral_code)
        if not affiliate:
            return {'success': False, 'error': f'Referral code not found: {referral_code}'}

        referral = {
            'id': str(uuid.uuid4()),
            'lead_email': lead_email,
            'lead_name': lead_name,
            'source': source,
            'status': 'pending',
            'plan': None,
            'commission': 0.0,
            'referred_at': datetime.utcnow().isoformat(),
            'converted_at': None
        }
        affiliate['referrals'].append(referral)
        affiliate['total_referrals'] += 1
        self._save_affiliate(affiliate)

        return {
            'success': True,
            'referral_id': referral['id'],
            'affiliate_id': affiliate['id'],
            'affiliate_name': affiliate['name']
        }

    def record_conversion(self, referral_code: str, lead_email: str,
                          plan: str = 'pro') -> Dict:
        """Mark a referral as converted and calculate commission"""
        affiliate = self._find_by_code(referral_code)
        if not affiliate:
            return {'success': False, 'error': f'Referral code not found: {referral_code}'}

        plan = plan.lower()
        plan_price = PLAN_PRICES.get(plan, 99)
        commission_rate = COMMISSION_RATES.get(plan, 0.20)
        commission = round(plan_price * commission_rate, 2)

        # Update the matching referral entry
        updated = False
        for referral in affiliate['referrals']:
            if referral['lead_email'] == lead_email and referral['status'] == 'pending':
                referral['status'] = 'converted'
                referral['plan'] = plan
                referral['commission'] = commission
                referral['converted_at'] = datetime.utcnow().isoformat()
                updated = True
                break

        if not updated:
            # Referral not pre-registered – create on-the-fly
            affiliate['referrals'].append({
                'id': str(uuid.uuid4()),
                'lead_email': lead_email,
                'status': 'converted',
                'plan': plan,
                'commission': commission,
                'referred_at': datetime.utcnow().isoformat(),
                'converted_at': datetime.utcnow().isoformat()
            })

        affiliate['total_conversions'] += 1
        affiliate['total_commission_earned'] = round(
            affiliate['total_commission_earned'] + commission, 2
        )
        self._save_affiliate(affiliate)

        return {
            'success': True,
            'affiliate_id': affiliate['id'],
            'affiliate_name': affiliate['name'],
            'plan': plan,
            'commission': commission,
            'total_earned': affiliate['total_commission_earned']
        }

    def get_affiliate_stats(self, affiliate_id: str) -> Optional[Dict]:
        """Return statistics for a single affiliate"""
        affiliate = self._load_affiliate(affiliate_id)
        if not affiliate:
            return None

        unpaid = round(
            affiliate['total_commission_earned'] - affiliate['total_commission_paid'], 2
        )
        return {
            'id': affiliate['id'],
            'name': affiliate['name'],
            'email': affiliate['email'],
            'referral_code': affiliate['referral_code'],
            'total_referrals': affiliate['total_referrals'],
            'total_conversions': affiliate['total_conversions'],
            'conversion_rate': (
                round(affiliate['total_conversions'] / affiliate['total_referrals'], 4)
                if affiliate['total_referrals'] > 0 else 0.0
            ),
            'total_commission_earned': affiliate['total_commission_earned'],
            'total_commission_paid': affiliate['total_commission_paid'],
            'unpaid_commission': unpaid,
            'status': affiliate['status']
        }

    def process_payout(self, affiliate_id: str) -> Dict:
        """Mark unpaid commissions as paid (trigger actual payout via Stripe Connect)"""
        affiliate = self._load_affiliate(affiliate_id)
        if not affiliate:
            return {'success': False, 'error': 'Affiliate not found'}

        unpaid = round(
            affiliate['total_commission_earned'] - affiliate['total_commission_paid'], 2
        )
        if unpaid <= 0:
            return {'success': False, 'error': 'No unpaid commissions'}

        affiliate['total_commission_paid'] = affiliate['total_commission_earned']
        self._save_affiliate(affiliate)

        # TODO: Initiate Stripe Connect transfer to affiliate['payment_email']
        print(f"💸 Payout ${unpaid} to {affiliate['payment_email']}")
        return {
            'success': True,
            'affiliate_id': affiliate_id,
            'amount_paid': unpaid,
            'payment_email': affiliate['payment_email'],
            'paid_at': datetime.utcnow().isoformat()
        }

    def _find_by_code(self, referral_code: str) -> Optional[Dict]:
        """Scan S3 prefix to find affiliate by referral code.

        Note: this full-prefix scan is suitable for small affiliate programs
        (hundreds of affiliates). At larger scale, replace with a DynamoDB
        index mapping referral_code → affiliate_id.
        """
        try:
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=AFFILIATE_KEY_PREFIX):
                for obj in page.get('Contents', []):
                    data = json.loads(
                        s3.get_object(Bucket=S3_BUCKET, Key=obj['Key'])['Body'].read()
                    )
                    if data.get('referral_code') == referral_code:
                        return data
        except Exception as e:
            print(f"Affiliate lookup error: {e}")
        return None

    def leaderboard(self, limit: int = 10) -> List[Dict]:
        """Return top affiliates sorted by commission earned"""
        affiliates = []
        try:
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=AFFILIATE_KEY_PREFIX):
                for obj in page.get('Contents', []):
                    data = json.loads(
                        s3.get_object(Bucket=S3_BUCKET, Key=obj['Key'])['Body'].read()
                    )
                    affiliates.append({
                        'name': data['name'],
                        'referral_code': data['referral_code'],
                        'conversions': data['total_conversions'],
                        'commission_earned': data['total_commission_earned']
                    })
        except Exception as e:
            print(f"Leaderboard error: {e}")

        affiliates.sort(key=lambda x: x['commission_earned'], reverse=True)
        return affiliates[:limit]
