"""ML Lead Scoring Model using scikit-learn
Scores B2B leads on likelihood to convert based on firmographic and behavioural signals
"""
import os
import json
import pickle
import numpy as np
from datetime import datetime
from typing import Dict, List

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
import boto3
from aws_utils import get_s3_client

S3_MODEL_BUCKET = os.environ.get('S3_BUCKET', 'garcar-revenue-data')
S3_MODEL_KEY    = 'models/lead_scoring_model.pkl'

TITLE_SCORE = {
    'ceo': 1.0, 'cto': 0.95, 'chief technology officer': 0.95,
    'coo': 0.9, 'vp engineering': 0.85, 'vp product': 0.8,
    'director': 0.7, 'head of': 0.7, 'manager': 0.5,
    'engineer': 0.3, 'developer': 0.3,
    'owner': 1.0, 'president': 0.95, 'principal': 0.85,
    'founder': 0.95, 'general contractor': 0.9,
    'project manager': 0.75, 'vp operations': 0.8,
    'director of operations': 0.8,
}

INDUSTRY_SCORE = {
    'software': 1.0, 'information technology': 0.95,
    'computer software': 0.95, 'fintech': 0.9,
    'saas': 1.0, 'ai': 1.0, 'machine learning': 1.0,
    'ecommerce': 0.8, 'healthcare': 0.75, 'manufacturing': 0.6,
    'construction': 0.85, 'general contractor': 0.85,
    'retail': 0.55, 'other': 0.4,
}

HIGH_VALUE_TECH_STACK = {
    'salesforce', 'hubspot', 'stripe', 'aws', 'gcp', 'azure',
    'segment', 'mixpanel', 'amplitude', 'zendesk', 'intercom'
}


def _title_to_score(title: str) -> float:
    if not title:
        return 0.3
    t = title.lower()
    for key, score in TITLE_SCORE.items():
        if key in t:
            return score
    return 0.3

def _industry_to_score(industry: str) -> float:
    if not industry:
        return 0.4
    i = industry.lower()
    for key, score in INDUSTRY_SCORE.items():
        if key in i:
            return score
    return 0.4

def _employee_range_to_midpoint(employee_range) -> float:
    if employee_range is None:
        return 0.3
    if isinstance(employee_range, (int, float)):
        val = float(employee_range)
    else:
        try:
            parts = str(employee_range).replace(',', '').split('-')
            val = (float(parts[0]) + float(parts[-1])) / 2
        except (ValueError, IndexError):
            return 0.3
    return min(val / 500.0, 1.0)

def _tech_stack_score(technologies: List[str]) -> float:
    if not technologies:
        return 0.0
    matches = sum(1 for t in technologies if t.lower() in HIGH_VALUE_TECH_STACK)
    return min(matches / 5.0, 1.0)

def extract_features(lead: Dict) -> np.ndarray:
    return np.array([
        _title_to_score(lead.get('title')),
        _industry_to_score(lead.get('industry')),
        _employee_range_to_midpoint(lead.get('employee_range')),
        _tech_stack_score(lead.get('technologies', [])),
        1.0 if lead.get('email')          else 0.0,
        1.0 if lead.get('phone')          else 0.0,
        1.0 if lead.get('linkedin')       else 0.0,
        1.0 if lead.get('company_domain') else 0.0,
    ], dtype=np.float32)


class LeadScoringModel:
    """
    GradientBoosting classifier. Falls back to weighted heuristic if no trained model.
    """
    def __init__(self):
        self.model     = GradientBoostingClassifier(n_estimators=100, max_depth=4,
                                                    learning_rate=0.1, random_state=42)
        self.scaler    = StandardScaler()
        self.is_trained = False
        self._try_load_model()

    def _try_load_model(self):
        try:
            s3  = get_s3_client()
            obj = s3.get_object(Bucket=S3_MODEL_BUCKET, Key=S3_MODEL_KEY)
            payload = pickle.loads(obj['Body'].read())
            self.model     = payload['model']
            self.scaler    = payload['scaler']
            self.is_trained = True
            print('Loaded lead scoring model from S3')
        except Exception:
            print('No pre-trained model — using heuristic scoring')

    def _save_model(self):
        try:
            s3  = get_s3_client()
            buf = pickle.dumps({'model': self.model, 'scaler': self.scaler})
            s3.put_object(Bucket=S3_MODEL_BUCKET, Key=S3_MODEL_KEY, Body=buf)
        except Exception as e:
            print(f'Could not save model: {e}')

    def _heuristic_score(self, lead: Dict) -> float:
        features = extract_features(lead)
        weights  = np.array([0.25, 0.20, 0.15, 0.15, 0.10, 0.05, 0.05, 0.05])
        return float(np.dot(features, weights))

    def score(self, lead: Dict) -> float:
        if not self.is_trained:
            return self._heuristic_score(lead)
        feat = extract_features(lead).reshape(1, -1)
        return float(self.model.predict_proba(self.scaler.transform(feat))[0, 1])

    def score_batch(self, leads: List[Dict]) -> List[Dict]:
        if not leads:
            return []
        if self.is_trained:
            X      = np.array([extract_features(l) for l in leads])
            probs  = self.model.predict_proba(self.scaler.transform(X))[:, 1]
        else:
            X      = np.array([extract_features(l) for l in leads])
            weights = np.array([0.25, 0.20, 0.15, 0.15, 0.10, 0.05, 0.05, 0.05])
            probs  = np.dot(X, weights)
        result = [{'lead': l, 'score': round(float(p), 4)} for l, p in zip(leads, probs)]
        result.sort(key=lambda x: x['score'], reverse=True)
        return result

    def train(self, leads: List[Dict], labels: List[int]) -> Dict:
        if len(leads) < 10:
            return {'success': False, 'error': 'Need at least 10 labelled leads'}
        X = np.array([extract_features(l) for l in leads])
        y = np.array(labels)
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
        self.scaler.fit(X_tr)
        self.model.fit(self.scaler.transform(X_tr), y_tr)
        self.is_trained = True
        auc = roc_auc_score(y_te, self.model.predict_proba(
            self.scaler.transform(X_te))[:, 1]) if len(set(y_te)) > 1 else None
        self._save_model()
        return {'success': True, 'roc_auc': round(float(auc), 4) if auc else None,
                'trained_at': datetime.utcnow().isoformat()}


# ── LeadScorer: public API used by customer_acquisition_loop.py ──────────────
class LeadScorer:
    """
    Thin wrapper around LeadScoringModel that returns a 0-100 integer score.
    This is the class imported by customer_acquisition_loop.py.
    """
    def __init__(self):
        self._model = LeadScoringModel()

    def score_lead(self, lead: Dict) -> float:
        """Return a 0-100 score for a single lead dict."""
        return round(self._model.score(lead) * 100, 1)

    def score_batch(self, leads: List[Dict]) -> List[Dict]:
        """Score list of leads, return sorted list with 0-100 scores."""
        raw = self._model.score_batch(leads)
        for entry in raw:
            entry['score'] = round(entry['score'] * 100, 1)
        return raw
