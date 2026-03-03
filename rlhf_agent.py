"""Self-Improving Agent via Reinforcement Learning from Human Feedback (RLHF)
Collects feedback on agent decisions and fine-tunes decision weights over time
"""
import os
import json
import math
import random
import boto3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

s3 = boto3.client('s3')
S3_BUCKET = os.environ.get('S3_BUCKET', 'garcar-revenue-data')
FEEDBACK_PREFIX = 'rlhf/feedback/'
WEIGHTS_KEY = 'rlhf/policy_weights.json'

# Action space for the wealth orchestration agent
ACTIONS = [
    'acquire_leads',
    'score_leads',
    'send_email_nurture',
    'send_sms_outreach',
    'create_subscription_basic',
    'create_subscription_pro',
    'create_subscription_enterprise',
    'upsell_to_higher_tier',
    'send_winback',
    'skip'
]

# Initial uniform policy weights (log-probabilities will be updated via RLHF)
DEFAULT_WEIGHTS = {action: 0.0 for action in ACTIONS}

LEARNING_RATE = float(os.environ.get('RLHF_LEARNING_RATE', '0.05'))
DISCOUNT_FACTOR = float(os.environ.get('RLHF_DISCOUNT_FACTOR', '0.95'))


def _softmax(weights: Dict[str, float]) -> Dict[str, float]:
    """Compute softmax probabilities from raw weights"""
    values = list(weights.values())
    max_v = max(values)
    exps = {k: math.exp(v - max_v) for k, v in weights.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


class RLHFAgent:
    """
    Self-improving agent that:
    1. Selects actions via a learned policy (softmax over weights)
    2. Collects human/automated reward feedback
    3. Updates policy weights via a simplified policy gradient (REINFORCE)
    4. Persists the policy to S3 for durable improvement across invocations
    """

    def __init__(self):
        self.weights: Dict[str, float] = self._load_weights()
        self.episode_log: List[Dict] = []

    # ------------------------------------------------------------------
    # Policy persistence
    # ------------------------------------------------------------------

    def _load_weights(self) -> Dict[str, float]:
        """Load policy weights from S3, falling back to defaults"""
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=WEIGHTS_KEY)
            loaded = json.loads(obj['Body'].read())
            # Merge with defaults to handle new actions added after training
            weights = dict(DEFAULT_WEIGHTS)
            weights.update(loaded)
            print("✅ Loaded RLHF policy weights from S3")
            return weights
        except Exception:
            print("ℹ️  No saved policy found – using default weights")
            return dict(DEFAULT_WEIGHTS)

    def _save_weights(self):
        """Persist current policy weights to S3"""
        try:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=WEIGHTS_KEY,
                Body=json.dumps(self.weights, indent=2),
                ContentType='application/json'
            )
        except Exception as e:
            print(f"⚠️  Could not save weights: {e}")

    # ------------------------------------------------------------------
    # Policy API
    # ------------------------------------------------------------------

    def select_action(self, state: Dict, epsilon: float = 0.1) -> str:
        """
        Epsilon-greedy action selection using current policy.

        Args:
            state: dict describing the current environment state
            epsilon: exploration rate (0 = pure exploitation)
        """
        if random.random() < epsilon:
            # Exploration: random action
            return random.choice(ACTIONS)

        probs = _softmax(self.weights)
        # Context-aware filtering based on state
        available = self._filter_actions(state, probs)
        actions = list(available.keys())
        weights_list = list(available.values())
        chosen = random.choices(actions, weights=weights_list, k=1)[0]
        return chosen

    def _filter_actions(self, state: Dict, probs: Dict[str, float]) -> Dict[str, float]:
        """Filter action probabilities based on state context"""
        filtered = dict(probs)
        has_high_score = state.get('lead_score', 0) >= 0.75
        is_trial = state.get('is_trial', False)
        current_plan = state.get('current_plan')

        if not has_high_score:
            filtered.pop('send_sms_outreach', None)
            filtered.pop('create_subscription_enterprise', None)

        if not is_trial:
            filtered.pop('send_email_nurture', None)

        if current_plan == 'enterprise':
            filtered.pop('upsell_to_higher_tier', None)

        # Re-normalize
        total = sum(filtered.values())
        return {k: v / total for k, v in filtered.items()} if total > 0 else probs

    def record_feedback(self, action: str, state: Dict, reward: float,
                        feedback_source: str = 'automated') -> str:
        """
        Record a human or automated reward signal for an action.

        Args:
            action: the action that was taken
            state: state dict at time of action
            reward: scalar reward (+1 good, -1 bad, 0 neutral, can be fractional)
            feedback_source: 'human' | 'automated' | 'stripe_webhook'

        Returns:
            feedback_id for reference
        """
        import uuid
        feedback_id = str(uuid.uuid4())
        entry = {
            'id': feedback_id,
            'action': action,
            'state': state,
            'reward': reward,
            'feedback_source': feedback_source,
            'timestamp': datetime.utcnow().isoformat()
        }
        self.episode_log.append(entry)

        # Persist feedback record to S3
        try:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=f"{FEEDBACK_PREFIX}{feedback_id}.json",
                Body=json.dumps(entry, indent=2),
                ContentType='application/json'
            )
        except Exception as e:
            print(f"⚠️  Could not persist feedback: {e}")

        return feedback_id

    def update_policy(self) -> Dict:
        """
        Apply policy gradient (REINFORCE) update using episode log.
        Positive rewards increase action weight; negative rewards decrease it.

        Returns:
            dict with update statistics
        """
        if not self.episode_log:
            return {'updated': False, 'reason': 'No feedback in episode log'}

        # Compute discounted returns
        G = 0.0
        returns = []
        for entry in reversed(self.episode_log):
            G = entry['reward'] + DISCOUNT_FACTOR * G
            returns.insert(0, G)

        # Normalize returns to reduce variance
        mean_G = sum(returns) / len(returns)
        std_G = (sum((r - mean_G) ** 2 for r in returns) / len(returns)) ** 0.5 + 1e-8
        normalised = [(r - mean_G) / std_G for r in returns]

        # Gradient ascent on policy weights
        for entry, norm_return in zip(self.episode_log, normalised):
            action = entry['action']
            if action in self.weights:
                self.weights[action] += LEARNING_RATE * norm_return

        self._save_weights()

        stats = {
            'updated': True,
            'steps': len(self.episode_log),
            'mean_return': round(mean_G, 4),
            'policy_weights': {k: round(v, 4) for k, v in self.weights.items()},
            'updated_at': datetime.utcnow().isoformat()
        }

        # Clear episode log after update
        self.episode_log.clear()
        return stats

    def get_policy_summary(self) -> Dict:
        """Return current policy probabilities for inspection"""
        probs = _softmax(self.weights)
        sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)
        return {
            'action_probabilities': {k: round(v, 4) for k, v in sorted_probs},
            'top_action': sorted_probs[0][0],
            'learning_rate': LEARNING_RATE,
            'discount_factor': DISCOUNT_FACTOR,
            'episode_steps_pending': len(self.episode_log)
        }

    def load_historical_feedback(self, limit: int = 500) -> List[Dict]:
        """Load recent feedback records from S3 for offline analysis"""
        records = []
        try:
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=FEEDBACK_PREFIX):
                for obj in page.get('Contents', []):
                    data = json.loads(
                        s3.get_object(Bucket=S3_BUCKET, Key=obj['Key'])['Body'].read()
                    )
                    records.append(data)
                    if len(records) >= limit:
                        return records
        except Exception as e:
            print(f"Error loading feedback: {e}")
        return records

    def retrain_from_history(self, limit: int = 500) -> Dict:
        """
        Reload saved feedback from S3 and run a full policy update.
        Use this for periodic batch retraining (e.g., nightly Lambda job).
        """
        self.episode_log = self.load_historical_feedback(limit)
        if not self.episode_log:
            return {'updated': False, 'reason': 'No historical feedback found'}
        result = self.update_policy()
        result['source'] = 'historical_retrain'
        return result
