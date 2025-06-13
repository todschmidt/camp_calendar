import json
from camp_sync import lambda_handler

if __name__ == "__main__":
    # Simulate a basic Lambda event
    # In a real scenario, this might be a CloudWatch event, SQS message, etc.
    test_event = {
        "source": "com.mycompany.myapp.test",
        "detail-type": "Manual Test Trigger",
        "detail": {}
    }

    # Simulate a basic Lambda context object
    class LambdaContext:
        def __init__(self):
            self.function_name = "camp-calendar-sync-debug"
            self.function_version = "$LATEST"
            self.memory_limit_in_mb = 128
            self.aws_request_id = "test-request-id"

        def get_remaining_time_in_millis(self):
            return 30000  # 30 seconds

    test_context = LambdaContext()

    print("--- Starting Debug Runner ---")
    try:
        # Call the handler
        result = lambda_handler.lambda_handler(test_event, test_context)
        print("--- Handler Result ---")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print("--- Handler Execution Failed ---")
        print(f"Exception: {type(e).__name__}")
        print(f"Message: {e}")
    finally:
        print("--- Debug Runner Finished ---") 