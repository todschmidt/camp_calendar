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


def is_running_locally():
    """Check if the function is running locally vs in AWS Lambda."""
    # In AWS Lambda, AWS_LAMBDA_FUNCTION_NAME is always set
    # In local testing, this environment variable won't be set
    return not os.environ.get("AWS_LAMBDA_FUNCTION_NAME")


def get_local_credentials():
    """Get credentials from local environment variables when running locally."""
    if is_running_locally():
        print("🔧 Running locally - using local credential files")
        
        # Check if environment variables are set for local testing
        checkfront_path = os.environ.get("CHECKFRONT_CREDENTIALS_PATH")
        google_creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH")
        google_token_path = os.environ.get("GOOGLE_TOKEN_PATH")
        site_config_path = os.environ.get("SITE_CONFIG_PATH")
        
        if all([checkfront_path, google_creds_path, google_token_path, site_config_path]):
            print("✅ All credential paths found in environment variables")
            return {
                "checkfront_creds": checkfront_path,
                "google_creds": google_creds_path,
                "google_token": google_token_path,
                "site_config": site_config_path
            }
        else:
            print("⚠️  Some credential paths missing, falling back to AWS Secrets Manager")
            return None
    
    return None


def lambda_handler(event, context):
    """
    AWS Lambda handler function.
    
    This function fetches credentials from AWS Secrets Manager when running in AWS,
    or uses local credential files when running locally for testing.
    """
    # Log the raw event received by the handler to see its structure.
    print(f"Received event: {json.dumps(event)}")
    
    try:
        # Set log level from environment variable
        log_level_str = os.environ.get("LOG_LEVEL", "NORMAL").upper()
        try:
            logger.level = LogLevel[log_level_str]
            print(f"Log level set to: {log_level_str}")
        except KeyError:
            logger.level = LogLevel.NORMAL
            print(f"WARN: Invalid LOG_LEVEL '{log_level_str}'. "
                  f"Defaulting to NORMAL.")
        
        # Try to get local credentials first
        local_creds = get_local_credentials()
        
        if local_creds:
            # Use local credential files
            print("📁 Using local credential files")
            checkfront_path = local_creds["checkfront_creds"]
            google_creds_path = local_creds["google_creds"]
            google_token_path = local_creds["google_token"]
            site_config_path = local_creds["site_config"]
            
            # Verify files exist and are readable
            for name, path in [
                ("Checkfront credentials", checkfront_path),
                ("Google credentials", google_creds_path),
                ("Google token", google_token_path),
                ("Site configuration", site_config_path)
            ]:
                if os.path.exists(path):
                    try:
                        with open(path, 'r') as f:
                            content = f.read()
                            if content.strip() and content != '{}':
                                print(f"✅ {name}: {path} (size: {len(content)} chars)")
                            else:
                                print(f"⚠️  {name}: {path} (empty or placeholder)")
                    except Exception as e:
                        print(f"❌ {name}: {path} (read error: {e})")
                else:
                    print(f"❌ {name}: {path} (file not found)")
            
        else:
            # Use AWS Secrets Manager (production mode)
            print("☁️  Using AWS Secrets Manager")
            checkfront_creds = get_secret("checkfront_credentials")
            google_creds = get_secret("google_credentials")
            google_token = get_secret("google_token")
            site_config = get_secret("site_configuration")

            # The core script expects credentials to be in files.
            # We'll write them to the /tmp/ directory, which is writable in Lambda.
            checkfront_path = "/tmp/checkfront_credentials.json"
            google_creds_path = "/tmp/google_credentials.json"
            google_token_path = "/tmp/token.json"
            site_config_path = "/tmp/site_configuration.json"

            with open(checkfront_path, "w") as f:
                f.write(checkfront_creds)
            with open(google_creds_path, "w") as f:
                f.write(google_creds)
            with open(google_token_path, "w") as f:
                f.write(google_token)
            with open(site_config_path, "w") as f:
                f.write(site_config)

        # Set environment variables to point to the credential files
        os.environ["CHECKFRONT_CREDENTIALS_PATH"] = checkfront_path
        os.environ["GOOGLE_CREDENTIALS_PATH"] = google_creds_path
        os.environ["GOOGLE_TOKEN_PATH"] = google_token_path
        os.environ["SITE_CONFIG_PATH"] = site_config_path

        print("Starting calendar sync process...")
        
        # Add detailed event dumps for debugging
        print("\n" + "="*60)
        print("🔍 DEBUG: EVENT DUMP BEFORE SYNC")
        print("="*60)
        
        # Import the core functions to get event counts and details
        from core import fetch_hipcamp_events, fetch_checkfront_events, logger as core_logger
        
        try:
            # Get and dump HipCamp events
            print("\n📋 HIPCAMP EVENTS:")
            hipcamp_events = fetch_hipcamp_events()
            print(f"   Total HipCamp events found: {len(hipcamp_events)}")
            for i, event in enumerate(hipcamp_events[:5]):  # Show first 5 events
                print(f"   {i+1}. {event.summary} (ID: {getattr(event, 'source_id', 'N/A')}) "
                      f"Date: {getattr(event, 'start_time', 'N/A')} to {getattr(event, 'end_time', 'N/A')}")
            if len(hipcamp_events) > 5:
                print(f"   ... and {len(hipcamp_events) - 5} more events")
            
            # Get and dump Checkfront events
            print("\n📋 CHECKFRONT EVENTS:")
            checkfront_events = fetch_checkfront_events()
            print(f"   Total Checkfront events found: {len(checkfront_events)}")
            for i, event in enumerate(checkfront_events[:5]):  # Show first 5 events
                print(f"   {i+1}. {event.summary} (ID: {getattr(event, 'source_id', 'N/A')}) "
                      f"Date: {getattr(event, 'start_time', 'N/A')} to {getattr(event, 'end_time', 'N/A')}")
            if len(checkfront_events) > 5:
                print(f"   ... and {len(checkfront_events) - 5} more events")
                
        except Exception as e:
            print(f"⚠️  Warning: Could not dump events for debugging: {e}")
        
        print("="*60)
        print("🔄 STARTING SYNC PROCESS")
        print("="*60)
        
        run_sync()
        print("Calendar sync process finished successfully.")

        return {
            'statusCode': 200,
            'body': json.dumps('Sync completed successfully!')
        }
    except Exception as e:
        # Use the configured logger to log the exception
        error_message = f"FATAL: An unhandled exception occurred: {e}"
        try:
            core_logger.warn(error_message)
        except:
            # Fallback to print if logger fails
            pass
        # Also print, in case the logger itself is the problem
        print(error_message)
        # Re-raise the exception to ensure the Lambda execution 
        # is marked as a failure
        raise 