"""Twilio SMS Outreach for High-Value Leads
Automated SMS sequences targeting leads with high ML lead scores
"""
import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

SCORE_THRESHOLD_SMS = float(os.environ.get('SMS_SCORE_THRESHOLD', '0.75'))

SMS_TEMPLATES = {
    'high_value_intro': (
        "Hi {name}, this is Garcar AI – we noticed {company} is scaling fast. "
        "Our platform automates your revenue pipeline from lead to close. "
        "Free 14-day trial: {trial_url} Reply STOP to opt out."
    ),
    'trial_ending': (
        "Hi {name}, your Garcar trial ends in 48 hrs. "
        "Upgrade now and keep your automations running: {upgrade_url} "
        "Reply STOP to opt out."
    ),
    'upsell_enterprise': (
        "Hi {name}, based on {company}'s growth we think Enterprise ($299/mo) "
        "fits your scale. Let's talk – book 15 min: {calendar_url} "
        "Reply STOP to opt out."
    ),
    'winback': (
        "Hi {name}, your Garcar automations are paused. Reactivate today with "
        "20% off: {upgrade_url}?promo=WINBACK20 Reply STOP to opt out."
    )
}


class SMSOutreach:
    def __init__(self):
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        self.from_number = os.environ.get('TWILIO_FROM_NUMBER')
        self.trial_url = os.environ.get('TRIAL_URL', 'https://app.garcar.io/trial')
        self.upgrade_url = os.environ.get('UPGRADE_URL', 'https://app.garcar.io/upgrade')
        self.calendar_url = os.environ.get('CALENDAR_URL', 'https://cal.garcar.io/enterprise')
        self.client = Client(account_sid, auth_token) if account_sid and auth_token else None

    def _render(self, template_key: str, context: Dict) -> str:
        """Render SMS template with context variables"""
        template = SMS_TEMPLATES.get(template_key, '')
        context.setdefault('trial_url', self.trial_url)
        context.setdefault('upgrade_url', self.upgrade_url)
        context.setdefault('calendar_url', self.calendar_url)
        return template.format(**context)

    def send_sms(self, to_number: str, body: str) -> Dict:
        """Send a single SMS via Twilio"""
        if not self.client:
            print("Twilio client not initialized – check TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN")
            return {'success': False, 'error': 'Twilio not configured'}
        if not self.from_number:
            return {'success': False, 'error': 'TWILIO_FROM_NUMBER not set'}

        try:
            message = self.client.messages.create(
                body=body,
                from_=self.from_number,
                to=to_number
            )
            return {
                'success': True,
                'sid': message.sid,
                'status': message.status,
                'to': to_number
            }
        except TwilioRestException as e:
            print(f"Twilio error to {to_number}: {str(e)}")
            return {'success': False, 'error': str(e), 'to': to_number}

    def outreach_high_value_lead(self, lead: Dict, score: float) -> Optional[Dict]:
        """Send intro SMS to a high-value lead if score exceeds threshold"""
        if score < SCORE_THRESHOLD_SMS:
            return None

        phone = lead.get('phone')
        if not phone:
            return None

        body = self._render('high_value_intro', {
            'name': lead.get('name', 'there').split()[0],
            'company': lead.get('company', 'your company')
        })
        result = self.send_sms(phone, body)
        result['template'] = 'high_value_intro'
        result['lead_score'] = score
        return result

    def send_trial_ending_sms(self, lead: Dict) -> Optional[Dict]:
        """Send trial-ending reminder SMS"""
        phone = lead.get('phone')
        if not phone:
            return None

        body = self._render('trial_ending', {
            'name': lead.get('name', 'there').split()[0]
        })
        result = self.send_sms(phone, body)
        result['template'] = 'trial_ending'
        return result

    def send_enterprise_upsell_sms(self, lead: Dict) -> Optional[Dict]:
        """Send Enterprise upsell SMS to high-value existing customers"""
        phone = lead.get('phone')
        if not phone:
            return None

        body = self._render('upsell_enterprise', {
            'name': lead.get('name', 'there').split()[0],
            'company': lead.get('company', 'your company')
        })
        result = self.send_sms(phone, body)
        result['template'] = 'upsell_enterprise'
        return result

    def send_winback_sms(self, lead: Dict) -> Optional[Dict]:
        """Send win-back SMS to churned users"""
        phone = lead.get('phone')
        if not phone:
            return None

        body = self._render('winback', {
            'name': lead.get('name', 'there').split()[0]
        })
        result = self.send_sms(phone, body)
        result['template'] = 'winback'
        return result

    def bulk_outreach(self, scored_leads: List[Dict]) -> List[Dict]:
        """Send SMS to all high-value leads in batch.

        Args:
            scored_leads: list of dicts with keys 'lead' (lead dict) and 'score' (float 0-1).
        """
        results = []
        for entry in scored_leads:
            lead = entry.get('lead', {})
            score = entry.get('score', 0.0)
            result = self.outreach_high_value_lead(lead, score)
            if result:
                results.append(result)
        return results
