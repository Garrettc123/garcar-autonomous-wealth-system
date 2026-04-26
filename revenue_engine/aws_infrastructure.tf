# GARCAR REVENUE ENGINE — AWS Infrastructure
# Terraform: provision all AWS resources needed for autonomous revenue flow
# Apply with: terraform init && terraform apply

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region"    { default = "us-east-1" }
variable "account_id"    { description = "AWS Account ID" }
variable "stripe_webhook_url" { description = "URL where Stripe sends events" }

# ── SQS: Signal Queue ─────────────────────────────────────────────────────────
resource "aws_sqs_queue" "signal_queue" {
  name                       = "garcar-signal-queue"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 86400  # 24 hours
  receive_wait_time_seconds  = 20     # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.signal_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "signal_dlq" {
  name = "garcar-signal-dlq"
  message_retention_seconds = 1209600  # 14 days — for dead lead processing
}

# ── DynamoDB: Conversions Table ───────────────────────────────────────────────
resource "aws_dynamodb_table" "conversions" {
  name           = "garcar-conversions"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "persona_id"

  attribute { name = "persona_id" type = "S" }
  attribute { name = "deployed_at" type = "S" }
  attribute { name = "converted"  type = "S" }

  global_secondary_index {
    name            = "converted-index"
    hash_key        = "converted"
    range_key       = "deployed_at"
    projection_type = "ALL"
  }

  ttl { attribute_name = "ttl" enabled = true }
}

# ── DynamoDB: Reinvestment Ledger ─────────────────────────────────────────────
resource "aws_dynamodb_table" "reinvestment_ledger" {
  name         = "garcar-reinvestment-ledger"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "payment_intent_id"

  attribute { name = "payment_intent_id" type = "S" }
}

# ── EventBridge: Revenue Bus ──────────────────────────────────────────────────
resource "aws_cloudwatch_event_bus" "revenue_bus" {
  name = "garcar-revenue-bus"
}

# Rule: AdBudgetAllocation events → Lambda
resource "aws_cloudwatch_event_rule" "ad_budget" {
  name           = "garcar-ad-budget-allocation"
  event_bus_name = aws_cloudwatch_event_bus.revenue_bus.name
  event_pattern  = jsonencode({
    source      = ["garcar.reinvestment"]
    detail-type = ["AdBudgetAllocation"]
  })
}

# ── ECS Fargate: Revenue Engine Task ─────────────────────────────────────────
resource "aws_ecs_cluster" "garcar" {
  name = "garcar-revenue-cluster"
}

resource "aws_ecs_task_definition" "revenue_engine" {
  family                   = "garcar-revenue-engine"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "revenue-engine"
    image     = "${var.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/garcar-revenue-engine:latest"
    essential = true
    environment = [
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "SIGNAL_QUEUE_URL", value = aws_sqs_queue.signal_queue.url },
      { name = "EVENTBRIDGE_BUS_NAME", value = aws_cloudwatch_event_bus.revenue_bus.name }
    ]
    secrets = [
      { name = "STRIPE_SECRET_KEY",    valueFrom = "/garcar/stripe_secret_key" },
      { name = "OPENAI_API_KEY",       valueFrom = "/garcar/openai_api_key" },
      { name = "TWILIO_ACCOUNT_SID",   valueFrom = "/garcar/twilio_account_sid" },
      { name = "TWILIO_AUTH_TOKEN",    valueFrom = "/garcar/twilio_auth_token" },
      { name = "APOLLO_API_KEY",       valueFrom = "/garcar/apollo_api_key" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = "/garcar/revenue-engine"
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "engine"
      }
    }
  }])
}

# ── IAM Roles ─────────────────────────────────────────────────────────────────
resource "aws_iam_role" "ecs_task" {
  name = "garcar-ecs-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "ecs_task_policy" {
  name = "garcar-ecs-task-policy"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["sqs:*"], Resource = [aws_sqs_queue.signal_queue.arn, aws_sqs_queue.signal_dlq.arn] },
      { Effect = "Allow", Action = ["dynamodb:*"], Resource = [aws_dynamodb_table.conversions.arn, aws_dynamodb_table.reinvestment_ledger.arn, "${aws_dynamodb_table.conversions.arn}/index/*"] },
      { Effect = "Allow", Action = ["events:PutEvents"], Resource = aws_cloudwatch_event_bus.revenue_bus.arn },
      { Effect = "Allow", Action = ["ses:SendEmail", "ses:SendRawEmail"], Resource = "*" },
      { Effect = "Allow", Action = ["ssm:GetParameter", "ssm:GetParameters"], Resource = "arn:aws:ssm:*:${var.account_id}:parameter/garcar/*" }
    ]
  })
}

resource "aws_iam_role" "ecs_execution" {
  name = "garcar-ecs-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  managed_policy_arns = ["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]
}

output "signal_queue_url"     { value = aws_sqs_queue.signal_queue.url }
output "revenue_bus_arn"      { value = aws_cloudwatch_event_bus.revenue_bus.arn }
output "conversions_table"    { value = aws_dynamodb_table.conversions.arn }
