# Camp Calendar Sync

This project automatically synchronizes bookings from HipCamp to a central Google Calendar and Checkfront account. It is designed to run as a serverless application on AWS.

A key feature of this system is its ability to handle real-time booking notifications from Checkfront via webhooks, ensuring that new reservations are processed and reflected in Checkfront almost instantly.

The email gateway is set up so you can set up a forwarding rule from your email account to sync@<YOUR DOMAIN> which will trigger the sync process.

## Architecture

The application is deployed on AWS and orchestrated with Terraform. The architecture is designed to be event-driven, scalable, and resilient.

-   **API Gateway**: Acts as the public-facing endpoint for the Checkfront webhook. When a new booking is made, Checkfront sends a notification to this endpoint.
-   **Amazon SQS (Simple Queue Service)**: The API Gateway forwards incoming webhook payloads to an SQS queue. This decouples the ingestion of bookings from their processing, ensuring that no notifications are lost even if the processing logic fails or is temporarily unavailable.
-   **AWS Lambda**: This is the core of the application. The Lambda function is triggered by new messages in the SQS queue. It parses the booking information and then creates a corresponding reservation in Checkfront and an event in Google Calendar.
-   **Amazon SNS (Simple Notification Service)**: If the Lambda function fails to process a booking after several retries, the message is sent to a Dead-Letter Queue (DLQ). An SNS topic is subscribed to this DLQ, which then sends an email notification to an administrator, flagging the issue for manual intervention.
-   **Amazon EventBridge**: Triggers the Lambda function on a recurring schedule to perform routine checks, such as verifying credentials or syncing data that may have been missed.
-   **AWS Secrets Manager**: Securely stores all necessary credentials (Checkfront API keys, Google API tokens), which are fetched by the Lambda function at runtime.
-   **Terraform**: The entire AWS infrastructure is defined as code using Terraform, allowing for repeatable and 
automated deployments.

### Architectural Diagram

```
+----------------+      +-------------+      +-------------+      +-----------------+
| HipCamp        |----->| API Gateway |----->| SQS Queue   |----->| AWS Lambda      |
| (Webhook)      |      +-------------+      +-------------+      | (Processing)    |
+----------------+                                               +-------+---------+
                                                                         |
                                                                         |
                                                               +---------v---------+
                                                               | Checkfront API    |
                                                               +-------------------+
                                                               | Google Calendar   |
                                                               +-------------------+
```

---

## Project Structure

```
.
├── camp_sync/
│   ├── lambda_handler.py   # AWS Lambda entry point & core logic
│   └── requirements.txt    # Python dependencies
├── terraform/
│   ├── main.tf             # Main Terraform infrastructure definition
│   ├── variables.tf        # Variable definitions
│   ├── outputs.tf          # Output definitions
│   └── .tfvars.example     # Example variables file for sensitive data
└── .gitignore              # Files to ignore in version control
```

---

## Prerequisites

-   Python 3.9+
-   Terraform
-   AWS CLI, with credentials configured (`aws configure`)
-   Git Bash for Windows (to ensure shell scripts run correctly)

---

## Local Development

The script can still be run locally for testing. It will default to using local credential files if the corresponding environment variables are not set.

1.  **Install Dependencies**:
    ```bash
    pip install -r camp_sync/requirements.txt
    ```
2.  **Create Credential Files**:
    -   `checkfront_credentials.json`
    -   `google_credentials.json` (obtained from Google Cloud Console)
    -   `token.json` (generated automatically on the first run)
3.  **Run the script**:
    The `debug_runner.py` script allows you to simulate a webhook event by reading a payload from a local file (`temp.txt`).

    ```bash
    python debug_runner.py
    ```

---

## Monitoring and Notifications

### Failure Notifications

-   If the Lambda function repeatedly fails to process a message from the SQS queue, the message is moved to a Dead-Letter Queue (DLQ).
-   A CloudWatch Alarm monitors this DLQ. If a message appears, an SNS topic sends an email alert to the `notification_email` you provide.
-   **Action Required**: When you first deploy, AWS will send a confirmation email. You **must click the link** in this email to activate the alert subscription.

---

## Deployment to AWS

The application is deployed using Terraform.

### Step 1: Set Up AWS Secrets Manager

Before deploying, you must create and populate the secrets in AWS Secrets Manager. While the Terraform script will create the secret *placeholders*, you must manually add the secret values for security.

1.  **Apply Terraform First**: Run `terraform apply` once. It will create the secrets with placeholder values.
2.  **Navigate to Secrets Manager**: Go to the AWS Secrets Manager console in the correct region (`us-west-2`).
3.  **Populate each secret**: Find the secrets created by Terraform and edit their values.

#### Secret 1: `checkfront_credentials`

-   **Secret name**: `checkfront_credentials`
-   **Secret value**: Paste the JSON content from your local `checkfront_credentials.json` file.

    **Syntax Example**:
    ```json
    {
      "api_key": "YOUR_CHECKFRONT_API_KEY",
      "api_secret": "YOUR_CHECKFRONT_API_SECRET"
    }
    ```

#### Secret 2: `google_credentials`

-   **Secret name**: `google_credentials`
-   **Secret value**: Paste the JSON content from your local `google_credentials.json` file (the one you downloaded from the Google Cloud Console).

    **Syntax Example**:
    ```json
    {
      "installed": {
        "client_id": "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com",
        "project_id": "your-gcp-project-id",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "YOUR_CLIENT_SECRET",
        "redirect_uris": ["http://localhost"]
      }
    }
    ```

#### Secret 3: `google_token`

-   **Secret name**: `google_token`
-   **Secret value**: Paste the JSON content from your local `token.json` file, which was generated after you successfully ran the script locally for the first time.

    **Syntax Example**:
    ```json
    {
      "token": "your-access-token",
      "refresh_token": "your-refresh-token",
      "token_uri": "https://oauth2.googleapis.com/token",
      "client_id": "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com",
      "client_secret": "YOUR_CLIENT_SECRET",
      "scopes": ["https://www.googleapis.com/auth/calendar"],
      "expiry": "2023-10-27T12:00:00.000000Z"
    }
    ```

### Step 2: Configure Terraform Variables

Create a `terraform.tfvars` file in the `terraform` directory to store your sensitive and environment-specific variables. Do **not** commit this file to version control.

A `terraform.tfvars.example` is provided as a template:

```hcl
# terraform/terraform.tfvars

aws_region           = "us-west-2"
notification_email   = "your-email@example.com"
hipcamp_api_key      = "your-hipcamp-api-key"
```

### Step 3: Deploy with Terraform

Once the secrets are populated and variables are configured, you can deploy the infrastructure.

1.  **Navigate to the terraform directory**:
    ```bash
    cd terraform
    ```
2.  **Initialize Terraform**:
    ```bash
    terraform init
    ```
3.  **Apply the configuration**:
    ```bash
    terraform apply
    ```

Terraform will provision all the necessary AWS resources. After the deployment is complete, it will output the `api_gateway_endpoint`, which you will need to provide to HipCamp to set up the webhook.

## DNS Configuration for Email

To ensure that Amazon SES can correctly receive emails on your behalf, you need to configure several DNS records for your domain.

### 1. MX Record

This record directs your domain's incoming mail to the Amazon SES endpoint. Note that you must use the endpoint for an AWS region that supports SES email receiving, such as `us-east-1`.

| Type | Host/Name | Value                                     | Priority |
| :--- | :-------- | :---------------------------------------- | :------- |
| MX   | @ or `your-domain.com` | `inbound-smtp.us-east-1.amazonaws.com`      | 10       |

### 2. SES Domain Verification TXT Record

This record proves to AWS that you own the domain. The value for this record is provided in the Terraform output `ses_domain_verification_token`.

| Type | Host/Name                     | Value                                     |
| :--- | :---------------------------- | :---------------------------------------- |
| TXT  | `_amazonses.your-domain.com` | `value-from-terraform-output`             |

### 3. DMARC Record

A DMARC record is a standard that helps protect your domain from being used for email spoofing. While not strictly required for the trigger to work, it is highly recommended for security. A basic permissive record is shown below.

| Type | Host/Name                     | Value                                     |
| :--- | :---------------------------- | :---------------------------------------- |
| TXT  | `_dmarc.your-domain.com`      | `v=DMARC1; p=none;`                       |

**Note**: DNS changes can take up to 48 hours to propagate, but they are often visible much sooner. You can use tools like `nslookup` to check if your records are live.

---

## Troubleshooting

If you encounter issues, here are the primary places to look for logs and error information in AWS CloudWatch:

1.  **Lambda Function Logs**:
    *   **Log Group**: `/aws/lambda/camp-calendar-sync` (or your chosen `function_name`).
    *   **What to look for**: This is the best place to start. You'll find detailed execution logs from the Python script, including any errors encountered while processing bookings, calling Checkfront APIs, or interacting with Google Calendar.

2.  **API Gateway Access Logs**:
    *   **Log Group**: `/aws/api_gateway/camp-calendar-sync-webhook-api`.
    *   **What to look for**: These logs show every request made to your webhook endpoint. Check here to confirm that Checkfront is successfully sending webhook notifications. You can see the request details, source IP, and status codes.

3.  **SQS Dead-Letter Queue (DLQ)**:
    *   **Queue Name**: `camp-calendar-sync-dlq`.
    *   **What to look for**: If a message fails processing in the Lambda function multiple times, it will be sent to this queue. You should have an SNS alarm configured to notify you, but you can also manually inspect the queue in the AWS SQS console to see the failed message payloads. This is crucial for debugging persistent processing failures.

