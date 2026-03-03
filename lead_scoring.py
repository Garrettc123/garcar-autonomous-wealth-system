"""ML Lead Scoring Model using scikit-learn
Scores B2B leads on likelihood to convert based on firmographic and behavioural signals
"""
import os
import json
import pickle
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
import boto3

S3_MODEL_BUCKET = os.environ.get('S3_BUCKET', 'garcar-revenue-data')
S3_MODEL_KEY = 'models/lead_scoring_model.pkl'

# Seniority and title weights used for feature engineering
TITLE_SCORE = {
    'ceo': 1.0, 'cto': 0.95, 'chief technology officer': 0.95,
    'coo': 0.9, 'vp engineering': 0.85, 'vp product': 0.8,
    'director': 0.7, 'head of': 0.7, 'manager': 0.5,
    'engineer': 0.3, 'developer': 0.3
}

INDUSTRY_SCORE = {
    'software': 1.0, 'information technology': 0.95,
    'computer software': 0.95, 'fintech': 0.9,
    'saas': 1.0, 'ai': 1.0, 'machine learning': 1.0,
    'ecommerce': 0.8, 'healthcare': 0.75, 'manufacturing': 0.6,
    'retail': 0.55, 'other': 0.4
}

HIGH_VALUE_TECH_STACK = {
    'salesforce', 'hubspot', 'stripe', 'aws', 'gcp', 'azure',
    'segment', 'mixpanel', 'amplitude', 'zendesk', 'intercom'
}


def _title_to_score(title: str) -> float:
    """Convert job title to numeric seniority score"""
    if not title:
        return 0.3
    title_lower = title.lower()
    for key, score in TITLE_SCORE.items():
        if key in title_lower:
            return score
    return 0.3


def _industry_to_score(industry: str) -> float:
    """Convert industry string to numeric relevance score"""
    if not industry:
        return 0.4
    industry_lower = industry.lower()
    for key, score in INDUSTRY_SCORE.items():
        if key in industry_lower:
            return score
    return 0.4


def _employee_range_to_midpoint(employee_range) -> float:
    """Convert employee range string or int to normalised float"""
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
    # Normalize to 0-1: 500 employees ≈ 1.0
    return min(val / 500.0, 1.0)


def _tech_stack_score(technologies: List[str]) -> float:
    """Score based on known high-value technology adoption"""
    if not technologies:
        return 0.0
    matches = sum(1 for t in technologies if t.lower() in HIGH_VALUE_TECH_STACK)
    return min(matches / 5.0, 1.0)


def extract_features(lead: Dict) -> np.ndarray:
    """Extract a fixed-length feature vector from a lead dictionary"""
    features = np.array([
        _title_to_score(lead.get('title')),
        _industry_to_score(lead.get('industry')),
        _employee_range_to_midpoint(lead.get('employee_range')),
        _tech_stack_score(lead.get('technologies', [])),
        1.0 if lead.get('email') else 0.0,
        1.0 if lead.get('phone') else 0.0,
        1.0 if lead.get('linkedin') else 0.0,
        1.0 if lead.get('company_domain') else 0.0
    ], dtype=np.float32)
    return features


class LeadScoringModel:
    """
    GradientBoosting classifier that scores leads 0-1 on conversion likelihood.
    Falls back to heuristic scoring if no trained model is available.
    """

    def __init__(self):
        self.model: GradientBoostingClassifier = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42
        )
        self.scaler = StandardScaler()
        self.is_trained = False
        self._try_load_model()

    def _try_load_model(self):
        """Attempt to load a pre-trained model from S3"""
        try:
            s3 = boto3.client('s3')
            obj = s3.get_object(Bucket=S3_MODEL_BUCKET, Key=S3_MODEL_KEY)
            payload = pickle.loads(obj['Body'].read())
            self.model = payload['model']
            self.scaler = payload['scaler']
            self.is_trained = True
            print("✅ Loaded lead scoring model from S3")
        except Exception:
            print("ℹ️  No pre-trained model found – using heuristic scoring")

    def _save_model(self):
        """Persist the trained model to S3"""
        try:
            s3 = boto3.client('s3')
            payload = pickle.dumps({'model': self.model, 'scaler': self.scaler})
            s3.put_object(Bucket=S3_MODEL_BUCKET, Key=S3_MODEL_KEY, Body=payload)
            print("✅ Saved lead scoring model to S3")
        except Exception as e:
            print(f"⚠️  Could not save model to S3: {str(e)}")

    def train(self, leads: List[Dict], labels: List[int]) -> Dict:
        """Train the model on historical lead data.

        Args:
            leads: list of lead dicts
            labels: binary conversion labels (1 = converted, 0 = not)

        Returns:
            dict with training metrics
        """
        if len(leads) < 10:
            return {'success': False, 'error': 'Need at least 10 labelled leads to train'}

        X = np.array([extract_features(lead) for lead in leads])
        y = np.array(labels)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y if y.sum() > 1 else None
        )

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        self.model.fit(X_train_scaled, y_train)
        self.is_trained = True

        y_prob = self.model.predict_proba(X_test_scaled)[:, 1]
        auc = roc_auc_score(y_test, y_prob) if len(set(y_test)) > 1 else None

        self._save_model()

        return {
            'success': True,
            'samples_trained': len(X_train),
            'samples_tested': len(X_test),
            'roc_auc': round(float(auc), 4) if auc is not None else None,
            'trained_at': datetime.utcnow().isoformat()
        }

    def _heuristic_score(self, lead: Dict) -> float:
        """Rule-based score when no trained model is available"""
        features = extract_features(lead)
        weights = np.array([0.25, 0.20, 0.15, 0.15, 0.10, 0.05, 0.05, 0.05])
        return float(np.dot(features, weights))

    def score(self, lead: Dict) -> float:
        """Return a 0-1 conversion probability for a single lead"""
        if not self.is_trained:
            return self._heuristic_score(lead)

        features = extract_features(lead).reshape(1, -1)
        features_scaled = self.scaler.transform(features)
        prob = self.model.predict_proba(features_scaled)[0, 1]
        return float(prob)

    def score_batch(self, leads: List[Dict]) -> List[Dict]:
        """Score a list of leads and return them sorted by score descending"""
        scored = []
        for lead in leads:
            score = self.score(lead)
            scored.append({'lead': lead, 'score': round(score, 4)})
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored

    def get_high_value_leads(self, leads: List[Dict], threshold: float = 0.7) -> List[Dict]:
        """Return only leads that exceed the conversion-probability threshold"""
        return [
            entry for entry in self.score_batch(leads)
            if entry['score'] >= threshold
        ]
