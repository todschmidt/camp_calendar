# Specifies the AWS provider and region.
provider "aws" {
  region = var.aws_region
}

# Define backend for storing terraform state
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}

# Define variables
variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "us-west-2"
}

variable "function_name" {
  description = "The name of the Lambda function."
  type        = string
  default     = "camp-calendar-sync"
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
          aws_secretsmanager_secret.google_token.arn
        ]
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
    command = "./build_layer.sh"
    working_dir = path.module
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