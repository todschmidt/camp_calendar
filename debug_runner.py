#!/usr/bin/env python3
"""
Debug Runner for Camp Calendar Sync Lambda Function

This script allows you to test the Lambda function locally with different event
types and local credential files instead of AWS Secrets Manager.

Usage:
    python debug_runner.py [--event-type EVENT_TYPE] [--test-mode TEST_MODE]
    [--verbose]

Event Types:
    - cloudwatch: Simulate CloudWatch scheduled event (default)
    - sqs: Simulate SQS message event
    - api-gateway: Simulate API Gateway webhook event

Test Modes:
    - full: Run complete sync process (default)
    - checkfront-only: Test only Checkfront API calls
    - hipcamp-only: Test only HipCamp iCal fetching
    - google-only: Test only Google Calendar operations
    - dry-run: Test without making actual changes

Examples:
    python debug_runner.py --event-type sqs --test-mode dry-run
    python debug_runner.py --event-type cloudwatch --test-mode checkfront-only
    --verbose
"""

import json
import os
import sys
import argparse
import tempfile
import shutil
import traceback
from typing import Dict, Any

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CAMP_SYNC_DIR = os.path.join(SCRIPT_DIR, 'camp_sync')

# Add the camp_sync directory to the Python path
if CAMP_SYNC_DIR not in sys.path:
    sys.path.insert(0, CAMP_SYNC_DIR)

# Also add the parent directory to handle relative imports
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

print(f"🔍 Script directory: {SCRIPT_DIR}")
print(f"🔍 Camp sync directory: {CAMP_SYNC_DIR}")
print(f"🔍 Python path: {sys.path[:3]}...")

try:
    from camp_sync.lambda_handler import lambda_handler
    print("✅ Successfully imported lambda_handler")
except ImportError as e:
    print(f"❌ Error importing lambda_handler: {e}")
    print("🔍 Trying alternative import paths...")
    
    try:
        # Try importing directly from the lambda_handler.py file
        import lambda_handler
        print("✅ Successfully imported lambda_handler directly")
    except ImportError as e2:
        print(f"❌ Direct import also failed: {e2}")
        print("🔍 Checking if lambda_handler.py exists...")
        
        if os.path.exists(os.path.join(CAMP_SYNC_DIR, 'lambda_handler.py')):
            print("✅ lambda_handler.py file exists")
            print("🔍 Checking file permissions...")
            try:
                with open(os.path.join(CAMP_SYNC_DIR, 'lambda_handler.py'), 'r') as f:
                    first_line = f.readline().strip()
                    print(f"✅ File is readable, first line: {first_line}")
            except Exception as e3:
                print(f"❌ File read error: {e3}")
        else:
            print("❌ lambda_handler.py file not found")
        
        print("\n🔧 Troubleshooting steps:")
        print("1. Make sure you're running from the camp_calendar root directory")
        print("2. Check that camp_sync/lambda_handler.py exists")
        print("3. Verify Python environment and dependencies")
        print("4. Try running: python -c 'import sys; print(sys.path)'")
        sys.exit(1)


class MockLambdaContext:
    """Mock Lambda context object for local testing."""
    
    def __init__(self, timeout_seconds: int = 300):
        self.function_name = "camp-calendar-sync-debug"
        self.function_version = "$LATEST"
        self.memory_limit_in_mb = 512
        self.aws_request_id = "test-request-id"
        self.invoked_function_arn = (
            "arn:aws:lambda:us-west-2:123456789012:"
            "function:camp-calendar-sync-debug"
        )
        self.log_group_name = "/aws/lambda/camp-calendar-sync-debug"
        self.log_stream_name = "2024/01/01/[$LATEST]test-stream"
        self._timeout_seconds = timeout_seconds
        self._start_time = None
        
    def get_remaining_time_in_millis(self):
        """Return remaining time in milliseconds."""
        return self._timeout_seconds * 1000


def create_test_event(event_type: str) -> Dict[str, Any]:
    """Create a test event based on the specified type."""
    
    if event_type == "cloudwatch":
        return {
            "version": "0",
            "id": "test-event-id",
            "detail-type": "Scheduled Event",
            "source": "aws.events",
            "account": "123456789012",
            "time": "2024-01-01T00:00:00Z",
            "region": "us-west-2",
            "resources": [
                "arn:aws:events:us-west-2:123456789012:rule/test-rule"
            ],
            "detail": {}
        }
    
    elif event_type == "sqs":
        return {
            "Records": [
                {
                    "messageId": "test-message-id",
                    "receiptHandle": "test-receipt-handle",
                    "body": json.dumps({
                        "source": "manual-test",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "data": {"test": "data"}
                    }),
                    "attributes": {
                        "ApproximateReceiveCount": "1",
                        "SentTimestamp": "1640995200000",
                        "SenderId": "test-sender",
                        "ApproximateFirstReceiveTimestamp": "1640995200000"
                    },
                    "messageAttributes": {},
                    "md5OfBody": "test-md5",
                    "eventSource": "aws:sqs",
                    "eventSourceARN": (
                        "arn:aws:sqs:us-west-2:123456789012:test-queue"
                    ),
                    "awsRegion": "us-west-2"
                }
            ]
        }
    
    elif event_type == "api-gateway":
        return {
            "version": "2.0",
            "routeKey": "POST /sync",
            "rawPath": "/sync",
            "rawQueryString": "",
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "test-client"
            },
            "requestContext": {
                "http": {
                    "method": "POST",
                    "path": "/sync"
                },
                "requestId": "test-request-id"
            },
            "body": json.dumps({
                "source": "checkfront-webhook",
                "timestamp": "2024-01-01T00:00:00Z"
            }),
            "isBase64Encoded": False
        }
    
    else:
        raise ValueError(f"Unknown event type: {event_type}")


def setup_local_credentials() -> Dict[str, str]:
    """Set up local credential files and return their paths."""
    
    # Define credential file paths
    credential_files = {
        "checkfront_credentials.json": "CHECKFRONT_CREDENTIALS_PATH",
        "google_credentials.json": "GOOGLE_CREDENTIALS_PATH", 
        "token.json": "GOOGLE_TOKEN_PATH",
        "site_configuration.json": "SITE_CONFIG_PATH"
    }
    
    # Check if credential files exist
    missing_files = []
    for filename in credential_files.keys():
        if not os.path.exists(filename):
            missing_files.append(filename)
    
    if missing_files:
        print("⚠️  Warning: Missing credential files: "
              f"{', '.join(missing_files)}")
        print("   Some functionality may not work without these files.")
        print("   Copy from .example files and fill in your credentials.")
    
    # Create temporary directory for credentials
    temp_dir = tempfile.mkdtemp(prefix="camp_sync_")
    credential_paths = {}
    
    # Copy credential files to temp directory and set environment variables
    for filename, env_var in credential_files.items():
        if os.path.exists(filename):
            temp_path = os.path.join(temp_dir, filename)
            shutil.copy2(filename, temp_path)
            credential_paths[env_var] = temp_path
            os.environ[env_var] = temp_path
            print(f"✅ {filename} -> {temp_path}")
        else:
            # Create empty file to prevent errors
            temp_path = os.path.join(temp_dir, filename)
            with open(temp_path, 'w') as f:
                f.write('{}')
            credential_paths[env_var] = temp_path
            os.environ[env_var] = temp_path
            print(f"⚠️  Created empty {filename} at {temp_path}")
    
    return credential_paths


def cleanup_temp_files(temp_dir: str):
    """Clean up temporary credential files."""
    try:
        if isinstance(temp_dir, str) and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"🧹 Cleaned up temporary files in {temp_dir}")
        else:
            print(f"⚠️  Warning: Invalid temp_dir: {temp_dir}")
    except Exception as e:
        print(f"⚠️  Warning: Could not clean up {temp_dir}: {e}")


def run_test(event_type: str, test_mode: str, verbose: bool = False):
    """Run the Lambda function test."""
    
    print("🚀 Starting Lambda function test...")
    print(f"   Event Type: {event_type}")
    print(f"   Test Mode: {test_mode}")
    print(f"   Verbose: {verbose}")
    print()
    
    # Set environment variables for testing
    os.environ["AWS_REGION"] = "us-west-2"
    os.environ["LOG_LEVEL"] = "DEBUG" if verbose else "NORMAL"
    
    # Set test mode environment variable
    if test_mode != "full":
        os.environ["TEST_MODE"] = test_mode
    
    # Create test event
    try:
        test_event = create_test_event(event_type)
        print(f"📋 Created {event_type} test event")
        if verbose:
            print(json.dumps(test_event, indent=2))
    except Exception as e:
        print(f"❌ Failed to create test event: {e}")
        return False
    
    # Create mock context
    test_context = MockLambdaContext(timeout_seconds=300)
    print("🔧 Created mock Lambda context")
    
    # Set up local credentials
    try:
        credential_paths = setup_local_credentials()
        # Extract the temp directory from the first credential path
        temp_dir = os.path.dirname(next(iter(credential_paths.values())))
        print("🔑 Set up local credentials")
    except Exception as e:
        print(f"❌ Failed to set up credentials: {e}")
        return False
    
    try:
        print()
        print("=" * 60)
        print("🔄 EXECUTING LAMBDA FUNCTION")
        print("=" * 60)
        
        # Call the Lambda handler
        result = lambda_handler(test_event, test_context)
        
        print("=" * 60)
        print("✅ LAMBDA FUNCTION EXECUTED SUCCESSFULLY")
        print("=" * 60)
        
        if verbose:
            print("📊 Handler Result:")
            print(json.dumps(result, indent=2))
        else:
            print(f"📊 Status Code: {result.get('statusCode', 'N/A')}")
            print(f"📊 Body: {result.get('body', 'N/A')}")
        
        return True
        
    except Exception as e:
        print("=" * 60)
        print("❌ LAMBDA FUNCTION EXECUTION FAILED")
        print("=" * 60)
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Message: {e}")
        
        if verbose:
            print("\n📚 Full Traceback:")
            traceback.print_exc()
        
        return False
        
    finally:
        # Clean up temporary files
        cleanup_temp_files(temp_dir)


def main():
    """Main function to parse arguments and run tests."""
    
    parser = argparse.ArgumentParser(
        description="Debug runner for Camp Calendar Sync Lambda function",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python debug_runner.py                                    # Run with defaults
  python debug_runner.py --event-type sqs                   # Test SQS event
  python debug_runner.py --test-mode dry-run --verbose      # Dry run with verbose output
  python debug_runner.py --event-type api-gateway --test-mode checkfront-only
        """
    )
    
    parser.add_argument(
        "--event-type",
        choices=["cloudwatch", "sqs", "api-gateway"],
        default="cloudwatch",
        help="Type of event to simulate (default: cloudwatch)"
    )
    
    parser.add_argument(
        "--test-mode",
        choices=["full", "checkfront-only", "hipcamp-only", "google-only", "dry-run"],
        default="full",
        help="Test mode to run (default: full)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output including full tracebacks"
    )
    
    args = parser.parse_args()
    
    # Print banner
    print("🏕️  Camp Calendar Sync - Lambda Function Debug Runner")
    print("=" * 60)
    
    # Check if we're in the right directory
    if not os.path.exists("camp_sync"):
        print("❌ Error: 'camp_sync' directory not found!")
        print("   Please run this script from the camp_calendar root directory.")
        sys.exit(1)
    
    # Run the test
    success = run_test(args.event_type, args.test_mode, args.verbose)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 