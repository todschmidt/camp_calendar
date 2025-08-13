# Migration to S3 Backend for Terraform State

This guide explains how to migrate your Terraform state from local storage to the new S3 backend.

## Prerequisites

- AWS credentials configured (SSO or IAM user)
- Terraform CLI installed
- Access to the AWS account where resources will be created

## Step 1: Initialize the S3 Backend

First, you need to create the S3 bucket and DynamoDB table. Since the backend configuration references these resources, you'll need to create them first with a local backend.

1. **Temporarily comment out the S3 backend configuration** in `main.tf`:
   ```hcl
   terraform {
     # backend "s3" {
     #   bucket         = "camp-calendar-terraform-state"
     #   key            = "terraform.tfstate"
     #   region         = "us-west-2"
     #   dynamodb_table = "camp-calendar-terraform-state-lock"
     #   encrypt        = true
     # }
   }
   ```

2. **Run Terraform to create the S3 bucket and DynamoDB table**:
   ```bash
   cd camp_calendar/terraform
   terraform init
   terraform plan
   terraform apply
   ```

3. **Uncomment the S3 backend configuration** in `main.tf`

## Step 2: Migrate State to S3

1. **Initialize the S3 backend**:
   ```bash
   terraform init -migrate-state
   ```

2. **When prompted, confirm the migration** by typing `yes`

3. **Verify the migration**:
   ```bash
   terraform plan
   ```
   This should show no changes if the migration was successful.

## Step 3: Verify the Setup

1. **Check that state is now stored in S3**:
   ```bash
   terraform show
   ```

2. **Verify the S3 bucket contains your state file**:
   - Check the AWS S3 console for the bucket `camp-calendar-terraform-state`
   - Look for the file `terraform.tfstate`

3. **Verify DynamoDB table exists**:
   - Check the AWS DynamoDB console for the table `camp-calendar-terraform-state-lock`

## Benefits of S3 Backend

- **Team Collaboration**: Multiple team members can work on the same infrastructure
- **State Locking**: Prevents concurrent modifications that could corrupt state
- **Versioning**: S3 versioning provides backup and recovery capabilities
- **Encryption**: Server-side encryption protects sensitive state data
- **Access Control**: IAM policies can control who can access state files

## Security Features

The S3 bucket and DynamoDB table are configured with:
- **Encryption**: AES256 server-side encryption
- **Public Access Blocked**: No public access allowed
- **Versioning**: Enabled for backup and recovery
- **Lifecycle Protection**: Bucket cannot be accidentally deleted

## Troubleshooting

### Common Issues

1. **Access Denied**: Ensure your AWS credentials have permissions to:
   - Create and manage S3 buckets
   - Create and manage DynamoDB tables
   - Read/write to the specific bucket and table

2. **State Lock Issues**: If a state lock gets stuck:
   - Check the DynamoDB table for stuck locks
   - Manually delete the lock entry if necessary

3. **Backend Configuration Errors**: Ensure:
   - Bucket name matches exactly
   - Region is correct
   - DynamoDB table name matches exactly

### Rollback

If you need to rollback to local state:
1. Comment out the S3 backend configuration
2. Copy your state file from S3 to local directory
3. Run `terraform init` to reinitialize local backend

## Next Steps

After successful migration:
1. Remove the local `terraform.tfstate` file (it's now backed up in S3)
2. Update your CI/CD pipelines to use the S3 backend
3. Consider setting up state file encryption with KMS for additional security
4. Set up monitoring and alerting for the S3 bucket and DynamoDB table
