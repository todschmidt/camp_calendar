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

variable "notification_email" {
  description = "The email address to send DLQ failure notifications to."
  type        = string
}

variable "email_domain" {
  description = "The domain name to use for receiving trigger emails (e.g., example.com)."
  type        = string
}
