"""Zero-Touch Secrets Provisioner — Garcar

Single source of truth: AWS Systems Manager Parameter Store (encrypted).

Flow:
  1. On FIRST EVER run: needs AWS creds injected once (via OIDC or bootstrap).
  2. Reads all params from SSM path /garcar/*
  3. Auto-provisions what it can (OIDC role, SES, S3 bucket, IAM policy)
  4. Syncs every secret → GitHub Actions encrypted secrets (self-healing)
  5. Every subsequent run: reads SSM → syncs to GitHub → zero human input.

Add a new service key once:
    aws ssm put-parameter --name /garcar/STRIPE_SECRET_KEY --value sk_live_... \
        --type SecureString --overwrite
  ...and it flows everywhere automatically on next run.
"""

import os
import json
import base64
import boto3
import requests
from datetime import datetime
from typing import Dict

REGION      = os.environ.get('AWS_REGION', 'us-east-1')
SSM_PREFIX  = '/garcar/'
GH_TOKEN    = os.environ.get('GITHUB_TOKEN', '')
REPO        = os.environ.get('GITHUB_REPOSITORY', 'Garrettc123/garcar-autonomous-wealth-system')
GH_API      = 'https://api.github.com'
GH_HEADERS  = {
    'Authorization':        f'token {GH_TOKEN}',
    'Accept':               'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}

# Keys that can be seeded from well-known defaults (non-sensitive config)
DEFAULT_CONFIG = {
    'AWS_REGION':      REGION,
    'S3_BUCKET':       'garcar-revenue-data',
    'SES_SENDER_EMAIL':'noreply@garcar.io',
    'DASHBOARD_URL':   'https://app.garcar.io/dashboard',
    'UPGRADE_URL':     'https://app.garcar.io/upgrade',
    'TRIAL_URL':       'https://app.garcar.io/trial',
    'CALENDAR_URL':    'https://cal.garcar.io/enterprise',
    'MIN_LEAD_SCORE':  '60',
    'LEADS_PER_CYCLE': '50',
}


class SecretsProvisioner:
    def __init__(self):
        self.ssm    = boto3.client('ssm', region_name=REGION)
        self.iam    = boto3.client('iam', region_name=REGION)
        self.ses    = boto3.client('ses', region_name=REGION)
        self.s3     = boto3.client('s3',  region_name=REGION)
        self.bundle: Dict[str, str] = {}
        self.synced  = 0
        self.pending = []
        self.errors  = []

    # ─────────────────────────────────────────────────────────────────
    # SSM  →  in-memory bundle
    # ─────────────────────────────────────────────────────────────────
    def load_from_ssm(self):
        """Pull every /garcar/* SecureString into memory."""
        try:
            paginator = self.ssm.get_paginator('get_parameters_by_path')
            for page in paginator.paginate(
                Path=SSM_PREFIX, WithDecryption=True, Recursive=True
            ):
                for param in page['Parameters']:
                    key   = param['Name'].replace(SSM_PREFIX, '').upper()
                    value = param['Value']
                    self.bundle[key] = value
                    os.environ[key]  = value
            print(f'  Loaded {len(self.bundle)} keys from SSM.')
        except Exception as e:
            print(f'  SSM load error (may be first run): {e}')

    def store_in_ssm(self, key: str, value: str):
        """Write one key to SSM SecureString."""
        try:
            self.ssm.put_parameter(
                Name=f'{SSM_PREFIX}{key}',
                Value=value,
                Type='SecureString',
                Overwrite=True,
                Description=f'Garcar auto-provisioned — {datetime.utcnow().date()}',
            )
            self.bundle[key] = value
            os.environ[key]  = value
            print(f'    Stored {key} → SSM')
        except Exception as e:
            print(f'    Could not store {key} in SSM: {e}')
            self.errors.append(key)

    # ─────────────────────────────────────────────────────────────────
    # GitHub Actions secret sync
    # ─────────────────────────────────────────────────────────────────
    def sync_to_github(self):
        """Encrypt and push every bundle key to GitHub Actions secrets."""
        if not GH_TOKEN:
            print('  No GITHUB_TOKEN — skipping GitHub sync.')
            return
        try:
            from nacl import encoding, public

            pk_resp = requests.get(
                f'{GH_API}/repos/{REPO}/actions/secrets/public-key',
                headers=GH_HEADERS, timeout=10
            )
            pk_resp.raise_for_status()
            pk_data = pk_resp.json()
            pub_key = public.PublicKey(pk_data['key'].encode(), encoding.Base64Encoder())
            box     = public.SealedBox(pub_key)

            count = 0
            for env_key, value in self.bundle.items():
                if not value:
                    continue
                encrypted = base64.b64encode(box.encrypt(value.encode())).decode()
                r = requests.put(
                    f'{GH_API}/repos/{REPO}/actions/secrets/{env_key}',
                    headers=GH_HEADERS, timeout=10,
                    json={'encrypted_value': encrypted, 'key_id': pk_data['key_id']}
                )
                if r.status_code in (201, 204):
                    count += 1
                else:
                    print(f'    Warning: could not sync {env_key} ({r.status_code})')

            self.synced = count
            print(f'  Synced {count}/{len(self.bundle)} secrets → GitHub Actions.')

        except ImportError:
            print('  pynacl not installed. pip install pynacl')
        except Exception as e:
            print(f'  GitHub sync error: {e}')

    # ─────────────────────────────────────────────────────────────────
    # Auto-provision what AWS can do without API keys
    # ─────────────────────────────────────────────────────────────────
    def provision_defaults(self):
        """Write non-sensitive config defaults into SSM if not already there."""
        print('\n[Config defaults]')
        for key, value in DEFAULT_CONFIG.items():
            if not self.bundle.get(key):
                self.store_in_ssm(key, value)

    def provision_s3_bucket(self):
        print('\n[S3 Bucket]')
        bucket = self.bundle.get('S3_BUCKET', 'garcar-revenue-data')
        try:
            if REGION == 'us-east-1':
                self.s3.create_bucket(Bucket=bucket)
            else:
                self.s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={'LocationConstraint': REGION}
                )
            # Enable versioning and encryption
            self.s3.put_bucket_versioning(
                Bucket=bucket,
                VersioningConfiguration={'Status': 'Enabled'}
            )
            self.s3.put_bucket_encryption(
                Bucket=bucket,
                ServerSideEncryptionConfiguration={
                    'Rules': [{'ApplyServerSideEncryptionByDefault':
                               {'SSEAlgorithm': 'AES256'}}]
                }
            )
            print(f'  Created S3 bucket: {bucket}')
        except self.s3.exceptions.BucketAlreadyOwnedByYou:
            print(f'  S3 bucket {bucket} already exists.')
        except Exception as e:
            print(f'  S3 bucket error: {e}')
            self.errors.append('S3_BUCKET')

    def provision_oidc_role(self):
        print('\n[AWS OIDC Role]')
        role_name = 'garcar-github-actions-role'
        try:
            sts = boto3.client('sts', region_name=REGION)
            account_id = sts.get_caller_identity()['Account']
        except Exception as e:
            print(f'  Could not get account ID: {e}')
            return

        oidc_arn = f'arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com'
        trust = {
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Principal': {'Federated': oidc_arn},
                'Action': 'sts:AssumeRoleWithWebIdentity',
                'Condition': {
                    'StringLike':  {'token.actions.githubusercontent.com:sub': f'repo:{REPO}:*'},
                    'StringEquals':{'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com'},
                }
            }]
        }

        policies = [
            'arn:aws:iam::aws:policy/SecretsManagerReadWrite',
            'arn:aws:iam::aws:policy/AmazonSSMFullAccess',
            'arn:aws:iam::aws:policy/AmazonSESFullAccess',
            'arn:aws:iam::aws:policy/AWSLambda_FullAccess',
            'arn:aws:iam::aws:policy/AmazonS3FullAccess',
            'arn:aws:iam::aws:policy/IAMFullAccess',
        ]

        try:
            resp     = self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust),
                Description='Garcar GitHub Actions OIDC — no static keys',
                Tags=[{'Key': 'project', 'Value': 'garcar'}]
            )
            role_arn = resp['Role']['Arn']
            for p in policies:
                self.iam.attach_role_policy(RoleName=role_name, PolicyArn=p)
            print(f'  Created OIDC role: {role_arn}')
        except self.iam.exceptions.EntityAlreadyExistsException:
            role_arn = self.iam.get_role(RoleName=role_name)['Role']['Arn']
            print(f'  OIDC role already exists: {role_arn}')
        except Exception as e:
            print(f'  OIDC role error: {e}')
            self.errors.append('OIDC_ROLE')
            return

        self.store_in_ssm('LAMBDA_EXECUTION_ROLE_ARN', role_arn)
        self.store_in_ssm('OIDC_ROLE_ARN', role_arn)
        self.store_in_ssm('AWS_ACCOUNT_ID', account_id)

        # Register OIDC provider if not already there
        try:
            self.iam.create_open_id_connect_provider(
                Url='https://token.actions.githubusercontent.com',
                ClientIDList=['sts.amazonaws.com'],
                ThumbprintList=['6938fd4d98bab03faadb97b34396831e3780aea1'],
            )
            print('  OIDC provider registered.')
        except self.iam.exceptions.EntityAlreadyExistsException:
            print('  OIDC provider already registered.')
        except Exception as e:
            print(f'  OIDC provider note: {e}')

    def provision_ses(self):
        print('\n[AWS SES]')
        sender = self.bundle.get('SES_SENDER_EMAIL', 'noreply@garcar.io')
        try:
            attrs = self.ses.get_identity_verification_attributes(Identities=[sender])
            status = attrs['VerificationAttributes'].get(sender, {}).get('VerificationStatus', 'NotStarted')
            if status != 'Success':
                self.ses.verify_email_identity(EmailAddress=sender)
                print(f'  Verification email sent to {sender}')
                self.pending.append(f'SES: check {sender} inbox and click verify link')
            else:
                print(f'  SES {sender} already verified.')
        except Exception as e:
            print(f'  SES error: {e}')
            self.errors.append('SES_SENDER_EMAIL')

    def check_pending_keys(self):
        """Report which revenue-critical keys are still missing from SSM."""
        print('\n[Missing Revenue Keys]')
        REVENUE_KEYS = [
            'STRIPE_SECRET_KEY',
            'STRIPE_WEBHOOK_SECRET',
            'APOLLO_API_KEY',
            'OPENAI_API_KEY',
            'STRIPE_PRICE_PRO',
        ]
        HOW_TO_ADD = (
            'aws ssm put-parameter '
            '--name /garcar/{KEY} '
            '--value "YOUR_VALUE" '
            '--type SecureString '
            '--overwrite'
        )
        missing = [k for k in REVENUE_KEYS if not self.bundle.get(k)]
        if not missing:
            print('  All revenue keys present in SSM.')
            return
        print('  These keys are missing. Add each with:')
        print(f'  {HOW_TO_ADD}')
        print()
        for k in missing:
            print(f'    /garcar/{k}')
            self.pending.append(k)

    # ─────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────
    def run(self):
        print('\n' + '='*60)
        print('  GARCAR ZERO-TOUCH PROVISIONER')
        print('  ' + datetime.utcnow().isoformat() + 'Z')
        print('='*60)

        self.load_from_ssm()       # 1. Pull whatever is already in SSM
        self.provision_defaults()  # 2. Seed non-sensitive config
        self.provision_s3_bucket() # 3. Ensure S3 bucket exists
        self.provision_oidc_role() # 4. OIDC role so AWS keys are never needed again
        self.provision_ses()       # 5. Verify SES sender
        self.check_pending_keys()  # 6. Report missing API keys
        self.sync_to_github()      # 7. Push everything → GitHub Actions secrets

        print('\n' + '='*60)
        print(f'  Synced: {self.synced}  Pending: {len(self.pending)}  Errors: {len(self.errors)}')
        if self.pending:
            print('\n  One-time manual steps (then never again):')
            for p in self.pending:
                print(f'    • {p}')
        print('='*60 + '\n')
        return {'synced': self.synced, 'pending': self.pending, 'errors': self.errors}


if __name__ == '__main__':
    import sys
    p = SecretsProvisioner()

    if len(sys.argv) >= 3 and sys.argv[1] == '--set':
        # python secrets_provisioner.py --set KEY=value
        # Stores in SSM + syncs to GitHub immediately
        kv = sys.argv[2]
        if '=' in kv:
            k, v = kv.split('=', 1)
            p.load_from_ssm()
            p.store_in_ssm(k.strip(), v.strip())
            p.sync_to_github()
            print(f'  {k} stored in SSM and synced to GitHub.')
        else:
            print('Usage: python secrets_provisioner.py --set KEY=value')
    else:
        p.run()
