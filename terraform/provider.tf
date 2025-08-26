# Specifies the AWS provider and region.
provider "aws" {
  region = var.aws_region
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