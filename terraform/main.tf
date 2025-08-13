# Specifies the AWS provider and region.
provider "aws" {
  region = var.aws_region
}

# Create S3 bucket for Terraform state storage
resource "aws_s3_bucket" "terraform_state" {
  bucket = var.terraform_state_bucket_name

  # Prevent accidental deletion
  lifecycle {
    prevent_destroy = true
  }
}

# Enable versioning for the state bucket
resource "aws_s3_bucket_versioning" "terraform_state_versioning" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Enable server-side encryption for the state bucket
resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state_encryption" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block public access to the state bucket
resource "aws_s3_bucket_public_access_block" "terraform_state_public_access_block" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Create DynamoDB table for state locking
resource "aws_dynamodb_table" "terraform_state_lock" {
  name           = var.terraform_state_lock_table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

# Define backend for storing terraform state
terraform {
  backend "s3" {
    bucket         = "camp-calendar-terraform-state"
    key            = "terraform.tfstate"
    region         = "us-west-2"
    dynamodb_table = "camp-calendar-terraform-state-lock"
    encrypt        = true
  }
}

# Create an S3 bucket to store Lambda deployment packages.
# It's a best practice to version deployment artifacts.
resource "aws_s3_bucket" "lambda_deployments" {
  bucket = "camp-calendar-sync-lambda-deployments"

  # It's good practice to prevent accidental deletion of the bucket.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "lambda_deployments_versioning" {
  bucket = aws_s3_bucket.lambda_deployments.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Define secrets in AWS Secrets Manager to securely store credentials.
# These secrets will be populated manually with the contents of your JSON files.
resource "aws_secretsmanager_secret" "checkfront_credentials" {
  name = "checkfront_credentials"
  description = "Checkfront API key and secret."
}

resource "aws_secretsmanager_secret" "google_credentials" {
  name = "google_credentials"
  description = "Google API credentials (from google_credentials.json)."
}

resource "aws_secretsmanager_secret" "google_token" {
  name = "google_token"
  description = "Google API token (from token.json)."
}

resource "aws_secretsmanager_secret" "site_configuration" {
  name = "site_configuration"
  description = "Configuration for site mappings, iCal URLs, etc."
}

# IAM role for the Lambda function
resource "aws_iam_role" "lambda_exec_role" {
  name = "${var.function_name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM policy to allow logging and accessing secrets
resource "aws_iam_policy" "lambda_exec_policy" {
  name        = "${var.function_name}-policy"
  description = "IAM policy for Lambda to log to CloudWatch and read secrets."
  
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Effect   = "Allow",
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Action = [
          "secretsmanager:GetSecretValue"
        ],
        Effect   = "Allow",
        Resource = [
          aws_secretsmanager_secret.checkfront_credentials.arn,
          aws_secretsmanager_secret.google_credentials.arn,
          aws_secretsmanager_secret.google_token.arn,
          aws_secretsmanager_secret.site_configuration.arn
        ]
      },
      {
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ],
        Effect   = "Allow",
        Resource = aws_sqs_queue.sync_queue.arn
      }
    ]
  })
}

# Attach the policy to the role
resource "aws_iam_role_policy_attachment" "lambda_exec_policy_attachment" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_exec_policy.arn
}

# --- Lambda Function and Layer ---

# Use a null_resource with a local-exec provisioner to run the build script.
# This ensures our dependencies are packaged before we try to create the layer.
resource "null_resource" "build_lambda_layer" {
  # This trigger ensures the script runs if the requirements file changes.
  triggers = {
    requirements_hash = filemd5("../camp_sync/requirements.txt")
  }

  provisioner "local-exec" {
    command     = "./build_layer.sh"
    working_dir = path.module
    # On Windows, explicitly set the interpreter to Git Bash
    interpreter = ["C:/Program Files/Git/bin/bash.exe"]
  }
}

# Create the Lambda Layer from the generated zip file
resource "aws_lambda_layer_version" "python_dependencies" {
  layer_name = "${var.function_name}-dependencies"
  filename   = "dependencies.zip"
  # This source code hash will change when the zip file changes, prompting a new layer version
  source_code_hash = filebase64sha256("dependencies.zip")
  
  compatible_runtimes = ["python3.9"]

  # This dependency ensures the zip file exists before Terraform tries to create the layer
  depends_on = [null_resource.build_lambda_layer]
}

data "archive_file" "lambda_source_zip" {
  type        = "zip"
  source_dir  = "../camp_sync"
  output_path = "lambda_source.zip"
}

resource "aws_lambda_function" "sync_function" {
  function_name = var.function_name
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_handler.lambda_handler"
  runtime       = "python3.9"
  timeout       = 300 # 5 minutes

  filename         = data.archive_file.lambda_source_zip.output_path
  source_code_hash = data.archive_file.lambda_source_zip.output_base64sha256

  # Attach the layer to the function
  layers = [aws_lambda_layer_version.python_dependencies.arn]

  # Set environment variables for the Lambda function
  environment {
    variables = {
      LOG_LEVEL = "NORMAL"
    }
  }

  # The AWS_REGION is automatically available as an environment variable
  # in the Lambda runtime, so we don't need to set it manually.

  depends_on = [
    aws_iam_role_policy_attachment.lambda_exec_policy_attachment
  ]
}

# --- EventBridge Scheduler ---

# Rule to trigger the Lambda function every hour
resource "aws_cloudwatch_event_rule" "every_hour" {
  name                = "run-camp-sync-every-hour"
  description         = "Triggers the camp calendar sync Lambda every hour."
  schedule_expression = "rate(1 hour)"
}

# Target for the rule (our Lambda function)
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.every_hour.name
  target_id = "TriggerLambda"
  arn       = aws_lambda_function.sync_function.arn
}

# Permission for EventBridge to invoke the Lambda function
resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sync_function.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_hour.arn
}

# --- SQS Queues for Asynchronous Processing ---

# Create a Dead-Letter Queue (DLQ) to capture failed messages
resource "aws_sqs_queue" "sync_dlq" {
  name = "${var.function_name}-dlq"
}

# Create the main SQS queue that the Lambda will poll
resource "aws_sqs_queue" "sync_queue" {
  name                      = "${var.function_name}-queue"
  delay_seconds             = 0
  max_message_size          = 262144 # 256 KB
  message_retention_seconds = 86400  # 1 day
  visibility_timeout_seconds = 300   # Should be >= Lambda timeout

  # Configure the DLQ for messages that fail processing
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.sync_dlq.arn
    maxReceiveCount     = 3 # After 3 failures, send to DLQ
  })
}

# --- API Gateway for Webhook ---

# Create a log group for the API Gateway access logs.
resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/api_gateway/${aws_apigatewayv2_api.webhook_api.name}"
  retention_in_days = 30 # Set a retention period for the logs
}

# Create an HTTP API Gateway for the Checkfront webhook.
resource "aws_apigatewayv2_api" "webhook_api" {
  name          = "${var.function_name}-webhook-api"
  protocol_type = "HTTP"
  description   = "API Gateway to trigger sync from Checkfront webhook."
}

# The default stage is used to manage deployments. Auto-deploy is enabled.
resource "aws_apigatewayv2_stage" "default_stage" {
  api_id      = aws_apigatewayv2_api.webhook_api.id
  name        = "$default"
  auto_deploy = true

  # Add throttling as a basic security measure to prevent abuse.
  default_route_settings {
    throttling_burst_limit = 1 # Allow up to 1 concurrent requests
    throttling_rate_limit  = 1 # Sustain 1 requests per second
  }

  # Enable access logging and define a structured JSON format.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId",
      ip             = "$context.identity.sourceIp",
      requestTime    = "$context.requestTime",
      httpMethod     = "$context.httpMethod",
      routeKey       = "$context.routeKey",
      status         = "$context.status",
      protocol       = "$context.protocol",
      responseLength = "$context.responseLength"
    })
  }
}

# IAM role for API Gateway to allow it to send messages to our SQS queue.
resource "aws_iam_role" "api_gateway_sqs_role" {
  name = "${var.function_name}-api-gateway-sqs-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = {
        Service = "apigateway.amazonaws.com"
      }
    }]
  })
}

# IAM policy for the API Gateway role
resource "aws_iam_policy" "api_gateway_sqs_policy" {
  name   = "${var.function_name}-api-gateway-sqs-policy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action   = "sqs:SendMessage",
      Effect   = "Allow",
      Resource = aws_sqs_queue.sync_queue.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_sqs_attachment" {
  role       = aws_iam_role.api_gateway_sqs_role.name
  policy_arn = aws_iam_policy.api_gateway_sqs_policy.arn
}

# Modify the API Gateway integration to point to SQS instead of Lambda
resource "aws_apigatewayv2_integration" "sqs_integration" {
  api_id                 = aws_apigatewayv2_api.webhook_api.id
  integration_type       = "AWS_PROXY"
  integration_subtype    = "SQS-SendMessage"
  credentials_arn        = aws_iam_role.api_gateway_sqs_role.arn
  request_parameters = {
    "QueueUrl"    = aws_sqs_queue.sync_queue.id,
    "MessageBody" = "$request.body"
  }
}

resource "aws_apigatewayv2_route" "sync_route" {
  api_id    = aws_apigatewayv2_api.webhook_api.id
  route_key = "POST /sync"
  target    = "integrations/${aws_apigatewayv2_integration.sqs_integration.id}"
}

# Add an event source mapping to trigger the Lambda from the SQS queue
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.sync_queue.arn
  function_name    = aws_lambda_function.sync_function.arn
  batch_size       = 1 # Process one message at a time
}

# --- SNS and CloudWatch for DLQ Alerts ---

# Create an SNS topic to send email alerts
resource "aws_sns_topic" "dlq_alerts" {
  name = "${var.function_name}-dlq-alerts"
}

# Subscribe the provided email address to the SNS topic
resource "aws_sns_topic_subscription" "email_subscription" {
  topic_arn = aws_sns_topic.dlq_alerts.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# Create a CloudWatch alarm that triggers when messages are in the DLQ
resource "aws_cloudwatch_metric_alarm" "dlq_alarm" {
  alarm_name          = "${var.function_name}-dlq-alarm"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = "1"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = "60"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "Alarm when the sync function DLQ has messages."
  alarm_actions       = [aws_sns_topic.dlq_alerts.arn]

  dimensions = {
    QueueName = aws_sqs_queue.sync_dlq.name
  }
}

# --- SES for Email-to-SQS Trigger ---

# S3 bucket to store a copy of incoming emails for debugging purposes
resource "aws_s3_bucket" "ses_emails" {
  bucket = "camp-calendar-sync-ses-emails"
}

# Policy to allow SES to write to the new S3 bucket
resource "aws_s3_bucket_policy" "allow_ses_to_write" {
  bucket = aws_s3_bucket.ses_emails.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Sid    = "AllowSESPuts",
      Effect = "Allow",
      Principal = {
        Service = "ses.amazonaws.com"
      },
      Action    = "s3:PutObject",
      Resource  = "${aws_s3_bucket.ses_emails.arn}/*",
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}

# IAM Role for SNS to log delivery status to CloudWatch
resource "aws_iam_role" "sns_logging_role" {
  name = "${var.function_name}-sns-logging-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = {
        Service = "sns.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_policy" "sns_logging_policy" {
  name = "${var.function_name}-sns-logging-policy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      Effect   = "Allow",
      Resource = "arn:aws:logs:*:*:*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sns_logging_attachment" {
  role       = aws_iam_role.sns_logging_role.name
  policy_arn = aws_iam_policy.sns_logging_policy.arn
}

# SNS topic to receive emails from SES
resource "aws_sns_topic" "email_trigger_topic" {
  name = "${var.function_name}-email-trigger"

  # Log delivery status for SQS subscribers to CloudWatch
  sqs_success_feedback_role_arn    = aws_iam_role.sns_logging_role.arn
  sqs_failure_feedback_role_arn    = aws_iam_role.sns_logging_role.arn
  sqs_success_feedback_sample_rate = 100 # Log 100% of successes
}

# Allow SES to publish to the new SNS topic
resource "aws_sns_topic_policy" "allow_ses_publish" {
  arn    = aws_sns_topic.email_trigger_topic.arn
  policy = data.aws_iam_policy_document.ses_publish_policy.json
}

data "aws_iam_policy_document" "ses_publish_policy" {
  statement {
    actions   = ["SNS:Publish"]
    effect    = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }
    resources = [aws_sns_topic.email_trigger_topic.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_caller_identity" "current" {}

# Subscribe the main SQS queue to the email SNS topic
resource "aws_sns_topic_subscription" "sqs_email_subscription" {
  topic_arn = aws_sns_topic.email_trigger_topic.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.sync_queue.arn
  raw_message_delivery = true
}

# Explicitly grant the SNS topic permission to send messages to the SQS queue.
# This is often needed to ensure reliable message delivery.
resource "aws_sqs_queue_policy" "allow_sns_to_send" {
  queue_url = aws_sqs_queue.sync_queue.id
  policy    = data.aws_iam_policy_document.sqs_policy_for_sns.json
}

data "aws_iam_policy_document" "sqs_policy_for_sns" {
  statement {
    effect    = "Allow"
    actions   = ["SQS:SendMessage"]
    resources = [aws_sqs_queue.sync_queue.arn]
    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.email_trigger_topic.arn]
    }
  }
}

# Verify the domain in SES. You must add the verification token to your DNS records.
resource "aws_ses_domain_identity" "email_trigger_domain" {
  domain = var.email_domain
}

# Create a receipt rule set if one doesn't already exist
resource "aws_ses_receipt_rule_set" "main" {
  rule_set_name = "default-rule-set"
}

resource "aws_ses_active_receipt_rule_set" "main" {
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
}

# Create a rule to forward emails to the SNS topic
resource "aws_ses_receipt_rule" "email_to_sns" {
  name          = "${var.function_name}-email-trigger"
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
  recipients    = ["sync@${var.email_domain}"]
  enabled       = true
  scan_enabled  = true

  # Action 1: Send a notification to the SNS topic
  sns_action {
    position  = 1
    topic_arn = aws_sns_topic.email_trigger_topic.arn
  }

  # Action 2: Save a copy of the email to S3 for debugging
  s3_action {
    position     = 2
    bucket_name  = aws_s3_bucket.ses_emails.id
    object_key_prefix = "emails"
  }
}
