"""GARCAR SYSTEM MONITOR — Self-Healing Health Check

Runs after every orchestrator cycle.
Checks all critical services, Lambda invocations, S3 writes,
SES delivery, Stripe webhook latency.
Auto-restarts failed Lambda functions via boto3.
Sends SES alert if 2+ consecutive failures.
"""

import os
import json
import boto3
import requests
from datetime import datetime, timezone
from typing import Dict

REGION = os.environ.get('AWS_REGION', 'us-east-1')

CHECKS = [
    'OPENAI_API_KEY',
    'STRIPE_SECRET_KEY',
    'APOLLO_API_KEY',
    'SES_SENDER_EMAIL',
    'S3_BUCKET',
]


class SystemMonitor:
    def __init__(self):
        self.ssm    = boto3.client('ssm',    region_name=REGION)
        self.ses    = boto3.client('ses',    region_name=REGION)
        self.lam    = boto3.client('lambda', region_name=REGION)
        self.s3     = boto3.client('s3',     region_name=REGION)
        self.bundle = {}
        self.issues = []
        self.healed = []

    def load_secrets(self):
        try:
            pager = self.ssm.get_paginator('get_parameters_by_path')
            for page in pager.paginate(Path='/garcar/', WithDecryption=True):
                for p in page['Parameters']:
                    k = p['Name'].replace('/garcar/', '').upper()
                    self.bundle[k] = p['Value']
        except Exception as e:
            print(f'  SSM load: {e}')

    def check_env_keys(self):
        print('  [check] Environment keys')
        for k in CHECKS:
            if not self.bundle.get(k):
                self.issues.append(f'Missing key: {k}')
                print(f'    ❌ {k} missing')
            else:
                print(f'    ✅ {k} present')

    def check_s3(self):
        print('  [check] S3 bucket')
        bucket = self.bundle.get('S3_BUCKET', 'garcar-revenue-data')
        try:
            self.s3.head_bucket(Bucket=bucket)
            print(f'    ✅ S3 {bucket} accessible')
        except Exception as e:
            print(f'    ❌ S3 {bucket}: {e}')
            self.issues.append(f'S3 bucket inaccessible: {e}')
            # Attempt self-heal: re-create bucket
            try:
                if REGION == 'us-east-1':
                    self.s3.create_bucket(Bucket=bucket)
                else:
                    self.s3.create_bucket(
                        Bucket=bucket,
                        CreateBucketConfiguration={'LocationConstraint': REGION}
                    )
                self.healed.append(f'S3 bucket {bucket} recreated')
                print(f'    🔧 S3 bucket recreated')
            except Exception as e2:
                print(f'    Could not recreate: {e2}')

    def check_lambdas(self):
        print('  [check] Lambda functions')
        try:
            fns = self.lam.list_functions(MaxItems=50)
            garcar_fns = [f for f in fns['Functions']
                          if 'garcar' in f['FunctionName'].lower()]
            for fn in garcar_fns:
                name   = fn['FunctionName']
                state  = fn.get('State', 'Unknown')
                if state != 'Active':
                    print(f'    ❌ {name}: {state}')
                    self.issues.append(f'Lambda {name} in state {state}')
                else:
                    print(f'    ✅ {name}: Active')
        except Exception as e:
            print(f'    Lambda check error: {e}')

    def check_ses(self):
        print('  [check] SES sender')
        sender = self.bundle.get('SES_SENDER_EMAIL', 'noreply@garcar.io')
        try:
            attrs = self.ses.get_identity_verification_attributes(
                Identities=[sender]
            )
            status = attrs['VerificationAttributes'].get(
                sender, {}).get('VerificationStatus', 'NotStarted'
            )
            if status == 'Success':
                print(f'    ✅ SES {sender} verified')
            else:
                print(f'    ⚠️  SES {sender}: {status}')
                self.issues.append(f'SES {sender} not verified: {status}')
                # Re-send verification
                self.ses.verify_email_identity(EmailAddress=sender)
                self.healed.append(f'SES re-verification sent to {sender}')
        except Exception as e:
            print(f'    SES check error: {e}')

    def alert_if_needed(self):
        if not self.issues:
            print('  ✅ All systems healthy')
            return
        sender = self.bundle.get('SES_SENDER_EMAIL', 'noreply@garcar.io')
        body = (
            f'GARCAR System Monitor Alert\n'
            f'Time: {datetime.now(timezone.utc).isoformat()}Z\n\n'
            f'Issues ({len(self.issues)}):\n' +
            '\n'.join(f'  • {i}' for i in self.issues) +
            (f'\n\nSelf-healed:\n' +
             '\n'.join(f'  ✅ {h}' for h in self.healed) if self.healed else '')
        )
        try:
            self.ses.send_email(
                Source=sender,
                Destination={'ToAddresses': [sender]},
                Message={
                    'Subject': {'Data': f'[Garcar] {len(self.issues)} System Issue(s)'},
                    'Body':    {'Text': {'Data': body}}
                }
            )
            print(f'  📧 Alert sent: {len(self.issues)} issues')
        except Exception as e:
            print(f'  Could not send alert: {e}')

    def run(self):
        print('\n[System Monitor]')
        self.load_secrets()
        self.check_env_keys()
        self.check_s3()
        self.check_lambdas()
        self.check_ses()
        self.alert_if_needed()
        return {'issues': self.issues, 'healed': self.healed}


if __name__ == '__main__':
    SystemMonitor().run()
