output "webhook_url" {
  description = "The URL of the API Gateway endpoint for the HipCamp webhook."
  value       = aws_apigatewayv2_api.webhook_api.api_endpoint
}

output "ses_domain_verification_token" {
  description = "The token to add as a TXT record to your domain's DNS to verify domain ownership with SES."
  value       = aws_ses_domain_identity.email_trigger_domain.verification_token
} 