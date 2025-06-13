import json
import boto3
import os

from core import run_sync, logger, LogLevel


def get_secret(secret_name):
    """Fetches a secret from AWS Secrets Manager."""
    region_name = os.environ.get("AWS_REGION", "us-east-1")
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except Exception as e:
        print(f"Unable to fetch secret {secret_name}: {e}")
        raise e

    return get_secret_value_response['SecretString']


def lambda_handler(event, context):
    """
    AWS Lambda handler function.
    
    This function fetches credentials from AWS Secrets Manager,
    writes them to temporary files, and then runs the main sync logic.
    """
    # Log the raw event received by the handler to see its structure.
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Set log level from environment variable
        log_level_str = os.environ.get("LOG_LEVEL", "NORMAL").upper()
        log_level_str = "DEBUG"
        try:
            logger.level = LogLevel[log_level_str]
            print(f"Log level set to: {log_level_str}")
        except KeyError:
            logger.level = LogLevel.NORMAL
            print(f"WARN: Invalid LOG_LEVEL '{log_level_str}'. "
                  f"Defaulting to NORMAL.")
            
        # Fetch credentials from Secrets Manager
        checkfront_creds = get_secret("checkfront_credentials")
        google_creds = get_secret("google_credentials")
        google_token = get_secret("google_token")

        # The core script expects credentials to be in files.
        # We'll write them to the /tmp/ directory, which is writable in Lambda.
        checkfront_path = "/tmp/checkfront_credentials.json"
        google_creds_path = "/tmp/google_credentials.json"
        google_token_path = "/tmp/token.json"

        with open(checkfront_path, "w") as f:
            f.write(checkfront_creds)
        with open(google_creds_path, "w") as f:
            f.write(google_creds)
        with open(google_token_path, "w") as f:
            f.write(google_token)

        # Set environment variables to point to the temp credential files
        os.environ["CHECKFRONT_CREDENTIALS_PATH"] = checkfront_path
        os.environ["GOOGLE_CREDENTIALS_PATH"] = google_creds_path
        os.environ["GOOGLE_TOKEN_PATH"] = google_token_path

        print("Starting calendar sync process...")
        run_sync()
        print("Calendar sync process finished successfully.")

        return {
            'statusCode': 200,
            'body': json.dumps('Sync completed successfully!')
        }
    except Exception as e:
        # Use the configured logger to log the exception
        error_message = f"FATAL: An unhandled exception occurred: {e}"
        logger.warn(error_message)
        # Also print, in case the logger itself is the problem
        print(error_message)
        # Re-raise the exception to ensure the Lambda execution 
        # is marked as a failure
        raise 