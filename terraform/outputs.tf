output "webhook_url" {
  description = "The URL of the API Gateway endpoint for the HipCamp webhook."
  value       = aws_apigatewayv2_api.webhook_api.api_endpoint
}

output "ses_domain_verification_token" {
  description = "The token to add as a TXT record to your domain's DNS to verify domain ownership with SES."
  value       = aws_ses_domain_identity.email_trigger_domain.verification_token
}

output "terraform_state_bucket_name" {
  description = "The name of the S3 bucket storing Terraform state files."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "terraform_state_bucket_arn" {
  description = "The ARN of the S3 bucket storing Terraform state files."
  value       = aws_s3_bucket.terraform_state.arn
}

output "terraform_state_lock_table_name" {
  description = "The name of the DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.terraform_state_lock.name
}

output "terraform_state_lock_table_arn" {
  description = "The ARN of the DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.terraform_state_lock.arn
} 