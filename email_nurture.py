"""AWS SES Email Nurture Sequences for Trial Conversion
Automates onboarding and conversion email campaigns for Garcar trial users
"""
import boto3
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

ses = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

NURTURE_SEQUENCES = {
    'trial_day_0': {
        'subject': 'Welcome to Garcar – Your 14-Day Trial Has Started 🚀',
        'delay_days': 0,
        'template': 'welcome_trial'
    },
    'trial_day_3': {
        'subject': 'Quick Win: 3 automations you can launch today',
        'delay_days': 3,
        'template': 'quick_wins'
    },
    'trial_day_7': {
        'subject': 'Halfway through your trial – here\'s your progress',
        'delay_days': 7,
        'template': 'midpoint_review'
    },
    'trial_day_11': {
        'subject': '3 days left – lock in your subscription and save',
        'delay_days': 11,
        'template': 'trial_ending_soon'
    },
    'trial_day_13': {
        'subject': 'Final 24 hours of your Garcar trial',
        'delay_days': 13,
        'template': 'last_chance'
    },
    'post_trial_winback': {
        'subject': 'We saved your account – come back and pick up where you left off',
        'delay_days': 2,
        'template': 'winback'
    }
}

EMAIL_TEMPLATES = {
    'welcome_trial': {
        'html': """
<html><body>
<h2>Welcome to Garcar Autonomous Wealth System!</h2>
<p>Hi {name},</p>
<p>Your 14-day free trial of the <strong>{plan_name}</strong> plan is now active.</p>
<p>Here's what you can do right now:</p>
<ul>
  <li>🔗 Connect your CRM and lead sources</li>
  <li>⚡ Launch your first automated revenue cycle</li>
  <li>📊 View real-time revenue metrics on your dashboard</li>
</ul>
<p><a href="{dashboard_url}">Go to Dashboard →</a></p>
<p>Questions? Reply to this email or visit our docs.</p>
<p>– The Garcar Team</p>
</body></html>
""",
        'text': "Welcome to Garcar! Your 14-day trial is active. Visit {dashboard_url} to get started."
    },
    'quick_wins': {
        'html': """
<html><body>
<h2>3 Quick Wins With Garcar</h2>
<p>Hi {name},</p>
<p>You're 3 days into your trial – here are three things you should try today:</p>
<ol>
  <li><strong>Run your first lead acquisition sweep</strong> – takes 2 minutes</li>
  <li><strong>Set up a Stripe subscription tier</strong> – monetise traffic automatically</li>
  <li><strong>Enable ML lead scoring</strong> – focus on the highest-value prospects</li>
</ol>
<p><a href="{dashboard_url}">Start Now →</a></p>
<p>– The Garcar Team</p>
</body></html>
""",
        'text': "Hi {name}, try these 3 quick wins: 1) Lead sweep, 2) Stripe tier, 3) ML scoring. Visit {dashboard_url}"
    },
    'midpoint_review': {
        'html': """
<html><body>
<h2>You're Halfway Through Your Garcar Trial</h2>
<p>Hi {name},</p>
<p>7 days in! Here's a summary of your activity so far.</p>
<p>To keep everything running after your trial, upgrade to a paid plan:</p>
<ul>
  <li><strong>Basic</strong> – $49/mo</li>
  <li><strong>Pro</strong> – $99/mo (most popular)</li>
  <li><strong>Enterprise</strong> – $299/mo</li>
</ul>
<p><a href="{upgrade_url}">Upgrade Now →</a></p>
<p>– The Garcar Team</p>
</body></html>
""",
        'text': "Hi {name}, 7 days in! Upgrade to Basic $49, Pro $99, or Enterprise $299 at {upgrade_url}"
    },
    'trial_ending_soon': {
        'html': """
<html><body>
<h2>Your Trial Ends in 3 Days</h2>
<p>Hi {name},</p>
<p>Don't lose your automated revenue pipeline. Upgrade before your trial expires and get:</p>
<ul>
  <li>Uninterrupted lead acquisition</li>
  <li>All active automations preserved</li>
  <li>Priority support</li>
</ul>
<p><a href="{upgrade_url}">Upgrade Now →</a></p>
<p>– The Garcar Team</p>
</body></html>
""",
        'text': "Your trial ends in 3 days, {name}. Upgrade at {upgrade_url} to keep your automations running."
    },
    'last_chance': {
        'html': """
<html><body>
<h2>Final 24 Hours – Act Now</h2>
<p>Hi {name},</p>
<p>Your trial expires tomorrow. After that, your automations will pause and leads will stop flowing.</p>
<p>Upgrade in the next 24 hours and we'll apply a <strong>10% first-month discount</strong>.</p>
<p><a href="{upgrade_url}?discount=TRIAL10">Claim Discount & Upgrade →</a></p>
<p>– The Garcar Team</p>
</body></html>
""",
        'text': "Final 24 hours, {name}! Get 10% off at {upgrade_url}?discount=TRIAL10"
    },
    'winback': {
        'html': """
<html><body>
<h2>We Saved Your Garcar Account</h2>
<p>Hi {name},</p>
<p>Your trial ended but your data and automations are still here. Come back and pick up where you left off.</p>
<p>We're offering you a special reactivation price for the next 48 hours.</p>
<p><a href="{upgrade_url}?promo=WINBACK20">Reactivate with 20% Off →</a></p>
<p>– The Garcar Team</p>
</body></html>
""",
        'text': "Hi {name}, your Garcar account is saved. Reactivate with 20% off at {upgrade_url}?promo=WINBACK20"
    }
}


class EmailNurtureSequencer:
    def __init__(self):
        self.sender = os.environ.get('SES_SENDER_EMAIL', 'noreply@garcar.io')
        self.dashboard_url = os.environ.get('DASHBOARD_URL', 'https://app.garcar.io/dashboard')
        self.upgrade_url = os.environ.get('UPGRADE_URL', 'https://app.garcar.io/upgrade')

    def _render_template(self, template_key: str, context: Dict) -> Dict:
        """Render email template with context variables"""
        template = EMAIL_TEMPLATES.get(template_key, {})
        context.setdefault('dashboard_url', self.dashboard_url)
        context.setdefault('upgrade_url', self.upgrade_url)
        context.setdefault('plan_name', 'Pro')

        html = template.get('html', '').format(**context)
        text = template.get('text', '').format(**context)
        return {'html': html, 'text': text}

    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str) -> Dict:
        """Send a single email via AWS SES"""
        try:
            response = ses.send_email(
                Source=self.sender,
                Destination={'ToAddresses': [to_email]},
                Message={
                    'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                    'Body': {
                        'Text': {'Data': text_body, 'Charset': 'UTF-8'},
                        'Html': {'Data': html_body, 'Charset': 'UTF-8'}
                    }
                }
            )
            return {'success': True, 'message_id': response['MessageId']}
        except Exception as e:
            print(f"SES send error to {to_email}: {str(e)}")
            return {'success': False, 'error': str(e)}

    def trigger_welcome_sequence(self, lead: Dict, plan_name: str = 'Pro') -> Dict:
        """Send day-0 welcome email immediately when trial starts"""
        sequence = NURTURE_SEQUENCES['trial_day_0']
        context = {
            'name': lead.get('name', 'there'),
            'plan_name': plan_name
        }
        rendered = self._render_template(sequence['template'], context)
        result = self.send_email(
            to_email=lead['email'],
            subject=sequence['subject'],
            html_body=rendered['html'],
            text_body=rendered['text']
        )
        result['sequence_step'] = 'trial_day_0'
        return result

    def trigger_conversion_sequence(self, lead: Dict, step: str) -> Dict:
        """Send a specific step in the nurture sequence"""
        if step not in NURTURE_SEQUENCES:
            return {'success': False, 'error': f'Unknown sequence step: {step}'}

        sequence = NURTURE_SEQUENCES[step]
        context = {'name': lead.get('name', 'there')}
        rendered = self._render_template(sequence['template'], context)
        result = self.send_email(
            to_email=lead['email'],
            subject=sequence['subject'],
            html_body=rendered['html'],
            text_body=rendered['text']
        )
        result['sequence_step'] = step
        return result

    def get_pending_sequence_steps(self, trial_start_date: datetime) -> List[str]:
        """Return which nurture steps are due based on trial start date"""
        now = datetime.utcnow()
        days_elapsed = (now - trial_start_date).days
        pending = []
        for step, config in NURTURE_SEQUENCES.items():
            if config['delay_days'] == days_elapsed:
                pending.append(step)
        return pending

    def send_bulk_nurture(self, leads_with_trial_info: List[Dict]) -> List[Dict]:
        """Process a batch of leads and send any due nurture emails"""
        results = []
        for entry in leads_with_trial_info:
            lead = entry.get('lead', {})
            trial_start = entry.get('trial_start')
            if not trial_start or not lead.get('email'):
                continue

            if isinstance(trial_start, str):
                trial_start = datetime.fromisoformat(trial_start)

            due_steps = self.get_pending_sequence_steps(trial_start)
            for step in due_steps:
                result = self.trigger_conversion_sequence(lead, step)
                result['lead_email'] = lead['email']
                results.append(result)

        return results

    def send_winback_email(self, lead: Dict) -> Dict:
        """Send win-back email to churned trial users"""
        return self.trigger_conversion_sequence(lead, 'post_trial_winback')
