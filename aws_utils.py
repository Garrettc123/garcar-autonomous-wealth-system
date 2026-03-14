"""AWS Client Utilities with Connection Pooling
Provides singleton boto3 clients with optimized connection pooling for better performance
"""
import boto3
from botocore.config import Config

# Configure connection pooling for all boto3 clients
# This reduces connection overhead and improves performance
_config = Config(
    max_pool_connections=50,  # Allow up to 50 concurrent connections per client
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'  # Adaptive retry mode for better reliability
    },
    connect_timeout=5,
    read_timeout=60
)

# Singleton clients - reuse across Lambda invocations
_s3_client = None
_kms_client = None
_lambda_client = None


def get_s3_client():
    """Get or create a pooled S3 client"""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client('s3', config=_config)
    return _s3_client


def get_kms_client():
    """Get or create a pooled KMS client"""
    global _kms_client
    if _kms_client is None:
        _kms_client = boto3.client('kms', config=_config)
    return _kms_client


def get_lambda_client():
    """Get or create a pooled Lambda client"""
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client('lambda', config=_config)
    return _lambda_client
