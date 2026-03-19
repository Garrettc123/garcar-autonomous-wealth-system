"""GARCAR PERFORMANCE AMPLIFIER

Reads every cycle's metrics from S3, computes trend deltas,
automatically tunes runtime parameters (lead volume, email cadence,
outreach timing) and writes updated config back to SSM.
Self-improves every run based on what actually worked.
"""

import os
import json
import boto3
from datetime import datetime, timezone
from typing import Dict, Any

REGION = os.environ.get('AWS_REGION', 'us-east-1')
BUCKET = os.environ.get('S3_BUCKET', 'garcar-revenue-data')


class PerformanceAmplifier:
    def __init__(self):
        self.s3  = boto3.client('s3',  region_name=REGION)
        self.ssm = boto3.client('ssm', region_name=REGION)

    def load_recent_metrics(self, n=10) -> list:
        try:
            resp = self.s3.list_objects_v2(Bucket=BUCKET, Prefix='metrics/')
            keys = sorted([o['Key'] for o in resp.get('Contents', [])],
                          reverse=True)[:n]
            metrics = []
            for k in keys:
                obj = self.s3.get_object(Bucket=BUCKET, Key=k)
                metrics.append(json.loads(obj['Body'].read()))
            return metrics
        except Exception as e:
            print(f'  [amplifier] Could not load metrics: {e}')
            return []

    def compute_deltas(self, history: list) -> Dict[str, Any]:
        if len(history) < 2:
            return {}
        latest = history[0]
        prev   = history[1]
        deltas = {}
        for k in ['leads_scraped', 'leads_qualified', 'emails_sent',
                  'sms_sent', 'revenue_events', 'errors']:
            l = latest.get(k, 0)
            p = prev.get(k, 0)
            if isinstance(l, list): l = len(l)
            if isinstance(p, list): p = len(p)
            deltas[k] = l - p
        return deltas

    def tune_parameters(self, deltas: Dict) -> Dict[str, str]:
        """Adjust runtime config based on performance delta."""
        config = {}

        # If lead quality dropping, increase score threshold
        lead_ratio = 0
        if deltas.get('leads_scraped', 0) > 0:
            lead_ratio = deltas.get('leads_qualified', 0) / deltas['leads_scraped']
        if lead_ratio > 0 and lead_ratio < 0.3:
            config['MIN_LEAD_SCORE'] = '70'  # raise bar
        elif lead_ratio > 0.6:
            config['MIN_LEAD_SCORE'] = '55'  # loosen bar — more volume

        # If email engagement flat, increase sends
        if deltas.get('emails_sent', 0) == 0:
            config['LEADS_PER_CYCLE'] = '75'
        elif deltas.get('revenue_events', 0) > 0:
            config['LEADS_PER_CYCLE'] = '100'  # scale on revenue signal
        else:
            config['LEADS_PER_CYCLE'] = '50'

        # If errors rising, reduce concurrency
        if deltas.get('errors', 0) > 3:
            config['MAX_CONCURRENT_TASKS'] = '2'
        else:
            config['MAX_CONCURRENT_TASKS'] = '5'

        config['LAST_TUNED'] = datetime.now(timezone.utc).isoformat() + 'Z'
        return config

    def apply_config(self, config: Dict[str, str]):
        """Write tuned config back to SSM so it flows everywhere on next run."""
        for key, value in config.items():
            try:
                self.ssm.put_parameter(
                    Name=f'/garcar/{key}',
                    Value=value,
                    Type='String',
                    Overwrite=True
                )
                print(f'  Tuned /garcar/{key} = {value}')
            except Exception as e:
                print(f'  Could not tune {key}: {e}')

    def run(self):
        print('\n[Performance Amplifier]')
        history = self.load_recent_metrics(10)
        if not history:
            print('  No history yet — skipping tuning.')
            return
        deltas = self.compute_deltas(history)
        print(f'  Deltas: {deltas}')
        config = self.tune_parameters(deltas)
        self.apply_config(config)
        print(f'  Applied {len(config)} parameter updates.')


if __name__ == '__main__':
    PerformanceAmplifier().run()
