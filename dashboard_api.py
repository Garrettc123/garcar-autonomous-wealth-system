"""Real-Time Revenue Dashboard API
Flask API endpoint exposing live revenue metrics for the Garcar Autonomous Wealth System
"""
import os
import json
import boto3
from datetime import datetime, timedelta
from typing import Dict, List
from flask import Flask, jsonify, request, abort
from functools import wraps

app = Flask(__name__)
s3 = boto3.client('s3')
S3_BUCKET = os.environ.get('S3_BUCKET', 'garcar-revenue-data')
DASHBOARD_API_KEY = os.environ.get('DASHBOARD_API_KEY', '')

PLAN_PRICES = {'basic': 49, 'pro': 99, 'enterprise': 299}


def require_api_key(f):
    """Simple API key authentication for dashboard endpoints"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if DASHBOARD_API_KEY and key != DASHBOARD_API_KEY:
            abort(401)
        return f(*args, **kwargs)
    return decorated


def _load_results(days: int = 30) -> List[Dict]:
    """Load daily result files from S3 for the past N days"""
    results = []
    today = datetime.utcnow().date()
    for i in range(days):
        day = today - timedelta(days=i)
        key = f"results/daily_{day.strftime('%Y%m%d')}.json"
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            data = json.loads(obj['Body'].read())
            data['date'] = day.isoformat()
            results.append(data)
        except Exception:
            pass
    return results


def _load_affiliates_summary() -> Dict:
    """Aggregate affiliate stats from S3"""
    total_referrals = 0
    total_conversions = 0
    total_commissions = 0.0
    count = 0
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix='affiliates/'):
            for obj in page.get('Contents', []):
                data = json.loads(
                    s3.get_object(Bucket=S3_BUCKET, Key=obj['Key'])['Body'].read()
                )
                total_referrals += data.get('total_referrals', 0)
                total_conversions += data.get('total_conversions', 0)
                total_commissions += data.get('total_commission_earned', 0.0)
                count += 1
    except Exception:
        pass
    return {
        'active_affiliates': count,
        'total_referrals': total_referrals,
        'total_conversions': total_conversions,
        'total_commissions_owed': round(total_commissions, 2)
    }


def _build_dashboard_payload(days: int = 30) -> Dict:
    """Assemble the full dashboard metrics payload"""
    results = _load_results(days)

    # Aggregate revenue metrics
    total_revenue = sum(r.get('revenue_generated', 0) for r in results)
    total_leads = sum(r.get('leads_acquired', 0) for r in results)
    total_subscriptions = sum(r.get('subscriptions_created', 0) for r in results)

    today_result = results[0] if results else {}
    today_revenue = today_result.get('revenue_generated', 0)

    # MRR estimate using Pro price as a conservative baseline.
    # For accurate MRR, query the Stripe subscriptions API with plan metadata.
    mrr_estimate = total_subscriptions * PLAN_PRICES.get('pro', 99)

    affiliates = _load_affiliates_summary()

    daily_series = [
        {'date': r.get('date'), 'revenue': r.get('revenue_generated', 0),
         'leads': r.get('leads_acquired', 0)}
        for r in reversed(results)
    ]

    return {
        'timestamp': datetime.utcnow().isoformat(),
        'period_days': days,
        'summary': {
            'revenue_today': today_revenue,
            'revenue_total': round(total_revenue, 2),
            'mrr_estimate': mrr_estimate,
            'leads_total': total_leads,
            'subscriptions_total': total_subscriptions,
            'conversion_rate': (
                round(total_subscriptions / total_leads, 4) if total_leads > 0 else 0.0
            )
        },
        'affiliates': affiliates,
        'daily_series': daily_series
    }


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})


@app.route('/api/v1/dashboard', methods=['GET'])
@require_api_key
def dashboard():
    """Real-time revenue dashboard metrics"""
    days = min(int(request.args.get('days', 30)), 90)
    payload = _build_dashboard_payload(days)
    return jsonify(payload)


@app.route('/api/v1/dashboard/summary', methods=['GET'])
@require_api_key
def dashboard_summary():
    """Quick summary – today's revenue and key KPIs"""
    payload = _build_dashboard_payload(days=1)
    return jsonify({
        'timestamp': payload['timestamp'],
        **payload['summary']
    })


@app.route('/api/v1/dashboard/affiliates', methods=['GET'])
@require_api_key
def dashboard_affiliates():
    """Affiliate performance overview"""
    return jsonify(_load_affiliates_summary())


if __name__ == '__main__':
    port = int(os.environ.get('DASHBOARD_PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
