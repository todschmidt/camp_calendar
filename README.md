# Camp Calendar Sync

This project automatically synchronizes bookings from HipCamp and Checkfront to a central Google Calendar. It is designed to run as a serverless function on AWS Lambda.

## Architecture

The application is deployed on AWS and uses the following services:

-   **AWS Lambda**: Hosts the Python script that performs the synchronization logic.
-   **Amazon EventBridge**: Triggers the Lambda function on a recurring schedule (e.g., every hour).
-   **AWS Lambda Layer**: Manages and packages all third-party Python dependencies (`requests`, `google-api-python-client`, etc.) to keep the main function code lightweight.
-   **AWS Secrets Manager**: Securely stores all necessary credentials (Checkfront API keys, Google API tokens), which are fetched by the Lambda function at runtime.
-   **Terraform**: The entire AWS infrastructure is defined as code using Terraform, allowing for repeatable and automated deployments.

---

## Project Structure

```
.
├── camp_sync/
│   ├── core.py             # Main application logic
│   ├── lambda_handler.py   # AWS Lambda entry point
│   └── requirements.txt    # Python dependencies
├── terraform/
│   ├── main.tf             # Terraform infrastructure definition
│   └── build_layer.sh      # Script to package dependencies for the Lambda Layer
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
    ```bash
    python camp_sync/core.py
    ```

---

## Monitoring and Manual Triggers

The system includes features for monitoring failures and manually triggering a sync.

### Failure Notifications

-   If the Lambda function repeatedly fails to process a message from Checkfront or via email, the message is sent to a Dead-Letter Queue (DLQ).
-   A CloudWatch Alarm monitors this DLQ. If a message appears in it, an email alert is sent to the `notification_email` you provide.
-   **Action Required**: Upon deploying, you will receive an email from AWS Notification. You **must click the confirmation link** in this email to activate the alert subscription.

### Manual Trigger via Email

You can manually start a sync process by sending an email to a configured address.

-   **Trigger Address**: `sync@your-domain.com` (where `your-domain.com` is the domain you provide).
-   The content of the email does not matter; the act of receiving it is what triggers the sync.

#### Email Trigger Setup

To enable this feature, you must prove to AWS that you own the domain.

1.  **Run `terraform apply`**: After applying the configuration, Terraform will output a value for `ses_domain_verification_token`.
2.  **Add a TXT Record**: Go to your DNS provider's control panel (e.g., GoDaddy, Namecheap, AWS Route 53) and add a new `TXT` record with the name `_amazonses.your-domain.com` and the value provided in the Terraform output.
3.  **Wait for Verification**: It may take up to 72 hours for AWS to see the DNS record and verify the domain, but it usually happens within an hour. You can check the status in the AWS SES console under "Verified identities".

Once the domain is verified, any email sent to the trigger address will start the sync process.

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

### Step 2: Deploy with Terraform

Once the secrets are populated, you can deploy the infrastructure.

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

Terraform will build the dependency layer, package the function, and create all the necessary AWS resources. Your function will now be live and running on an hourly schedule.
