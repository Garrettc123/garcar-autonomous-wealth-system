#!/bin/bash
# Deploy Garcar Autonomous Wealth System to AWS Lambda
# Run from Termux or any Unix environment with AWS CLI configured

set -e  # Exit on error

echo "🚀 Deploying Garcar Autonomous Wealth System..."

# Configuration
REGION="us-west-2"  # Dallas/Texas proximity
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME="garcar-lambda-execution-role"
BUCKET="garcar-revenue-data"

echo "📋 AWS Account: $ACCOUNT_ID"
echo "📍 Region: $REGION"

# Create S3 bucket for data storage
echo "\n📦 Creating S3 bucket..."
aws s3 mb s3://$BUCKET --region $REGION 2>/dev/null || echo "Bucket already exists"

# Create IAM role for Lambda
echo "\n🔐 Creating IAM execution role..."
cat > trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document file://trust-policy.json 2>/dev/null || echo "Role already exists"

# Attach policies
aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/AWSKeyManagementServicePowerUser

ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"
echo "✅ Role ARN: $ROLE_ARN"

# Package Python Lambda (Orchestrator)
echo "\n📦 Packaging Python orchestrator..."
mkdir -p build/python
pip install -t build/python \
  boto3 \
  langchain \
  openai \
  stripe \
  requests

cp agent_coordinator.py build/python/
cp linear_integration.py build/python/
cp lead_acquisition.py build/python/

cd build/python
zip -r ../orchestrator.zip . -q
cd ../..

echo "✅ Python package created: build/orchestrator.zip"

# Package Node.js Lambda (Revenue Agent)
echo "\n📦 Packaging Node.js revenue agent..."
mkdir -p build/nodejs
cp revenue_agent.js build/nodejs/index.js
cp package.json build/nodejs/

cd build/nodejs
npm install --production --silent
zip -r ../revenue_agent.zip . -q
cd ../..

echo "✅ Node.js package created: build/revenue_agent.zip"

# Create/Update Python Lambda
echo "\n🚀 Deploying orchestrator Lambda..."
aws lambda create-function \
  --function-name garcar-orchestrator \
  --runtime python3.11 \
  --role $ROLE_ARN \
  --handler agent_coordinator.lambda_handler \
  --zip-file fileb://build/orchestrator.zip \
  --timeout 300 \
  --memory-size 512 \
  --region $REGION \
  --environment "Variables={
    S3_BUCKET=$BUCKET,
    STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY,
    LINEAR_API_KEY=$LINEAR_API_KEY,
    LINEAR_TEAM_ID=$LINEAR_TEAM_ID,
    APOLLO_API_KEY=$APOLLO_API_KEY,
    OPENAI_API_KEY=$OPENAI_API_KEY
  }" 2>/dev/null || \
aws lambda update-function-code \
  --function-name garcar-orchestrator \
  --zip-file fileb://build/orchestrator.zip \
  --region $REGION

echo "✅ Orchestrator deployed"

# Create/Update Node.js Lambda
echo "\n🚀 Deploying revenue agent Lambda..."
aws lambda create-function \
  --function-name garcar-revenue-agent \
  --runtime nodejs18.x \
  --role $ROLE_ARN \
  --handler index.handler \
  --zip-file fileb://build/revenue_agent.zip \
  --timeout 300 \
  --memory-size 512 \
  --region $REGION \
  --environment "Variables={
    S3_BUCKET=$BUCKET,
    STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY,
    STRIPE_PRICE_ID=$STRIPE_PRICE_ID,
    STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_SECRET,
    LINEAR_API_KEY=$LINEAR_API_KEY,
    LINEAR_TEAM_ID=$LINEAR_TEAM_ID
  }" 2>/dev/null || \
aws lambda update-function-code \
  --function-name garcar-revenue-agent \
  --zip-file fileb://build/revenue_agent.zip \
  --region $REGION

echo "✅ Revenue agent deployed"

# Create EventBridge rule for daily execution (9 AM CST = 3 PM UTC)
echo "\n⏰ Setting up daily automation..."
aws events put-rule \
  --name garcar-daily-wealth-cycle \
  --schedule-expression "cron(0 15 * * ? *)" \
  --region $REGION \
  --description "Daily autonomous wealth generation cycle - 9 AM CST"

# Add Lambda permission for EventBridge
aws lambda add-permission \
  --function-name garcar-orchestrator \
  --statement-id garcar-daily-trigger \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:$REGION:$ACCOUNT_ID:rule/garcar-daily-wealth-cycle \
  --region $REGION 2>/dev/null || echo "Permission already exists"

# Add target to EventBridge rule
aws events put-targets \
  --rule garcar-daily-wealth-cycle \
  --targets "Id"="1","Arn"="arn:aws:lambda:$REGION:$ACCOUNT_ID:function:garcar-orchestrator" \
  --region $REGION

echo "✅ Daily automation configured (9 AM CST)"

# Test invocation
echo "\n🧪 Testing orchestrator..."
aws lambda invoke \
  --function-name garcar-orchestrator \
  --region $REGION \
  --payload '{}' \
  response.json

echo "\n📊 Response:"
cat response.json
echo "\n"

# Cleanup
rm -f trust-policy.json response.json
rm -rf build/

echo "\n✅ Deployment complete!"
echo "\n📈 System Status:"
echo "   - Orchestrator: https://console.aws.amazon.com/lambda/home?region=$REGION#/functions/garcar-orchestrator"
echo "   - Revenue Agent: https://console.aws.amazon.com/lambda/home?region=$REGION#/functions/garcar-revenue-agent"
echo "   - S3 Bucket: https://s3.console.aws.amazon.com/s3/buckets/$BUCKET"
echo "   - Daily Run: 9:00 AM CST (3:00 PM UTC)"
echo "\n💰 Next Steps:"
echo "   1. Set environment variables (see .env.example)"
echo "   2. Configure Stripe webhook endpoint"
echo "   3. Verify Linear integration"
echo "   4. Monitor first revenue cycle"
echo "\n🚀 Autonomous wealth generation is LIVE!"
