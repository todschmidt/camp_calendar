"""
AWS Lambda handler for Camp Calendar Sync.

This module provides the AWS Lambda handler for synchronizing
HipCamp and Checkfront reservations with Google Calendar.
"""

import datetime
import json
import os
from typing import Any, Dict, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .core import (
    LogLevel,
    Logger,
    get_google_credentials,
    fetch_hipcamp_events,
    fetch_checkfront_events,
    get_google_calendar_events,
    sync_events_to_calendar,
)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler function.
    
    This function:
    1. Loads configuration from environment variables
    2. Sets up logging
    3. Authenticates with Google Calendar API
    4. Finds the target calendar
    5. Fetches events from all sources
    6. Syncs the events
    
    Args:
        event: Lambda event data
        context: Lambda context
        
    Returns:
        Response dictionary with status and message
    """
    # Set up logging
    log_level = os.environ.get("LOG_LEVEL", "NORMAL")
    logger = Logger(LogLevel[log_level])
    
    try:
        # Load configuration from environment variables
        hipcamp_urls = json.loads(os.environ["HIPCAMP_URLS"])
        checkfront_url = os.environ["CHECKFRONT_URL"]
        calendar_name = os.environ.get("CALENDAR_NAME", "DBR Camping")
        
        # Get credentials from environment variables
        credentials_json = os.environ["GOOGLE_CREDENTIALS"]
        token_json = os.environ.get("GOOGLE_TOKEN")
        
        # Write credentials to temporary files
        credentials_path = "/tmp/credentials.json"
        token_path = "/tmp/token.json" if token_json else "/tmp/token.json"
        
        with open(credentials_path, "w") as f:
            f.write(credentials_json)
            
        if token_json:
            with open(token_path, "w") as f:
                f.write(token_json)
        
        # Get credentials without forcing refresh
        creds = get_google_credentials(
            credentials_path=credentials_path,
            token_path=token_path,
            force_refresh=False
        )
        
        # Build Google Calendar API service
        service = build("calendar", "v3", credentials=creds)
        
        # Find the target calendar
        logger.normal("Listing all calendars...")
        calendar_list = service.calendarList().list().execute()
        calendar_id = None
        
        for calendar in calendar_list.get('items', []):
            logger.debug(
                f"Calendar: {calendar['summary']} (ID: {calendar['id']})"
            )
            if calendar['summary'] == calendar_name:
                calendar_id = calendar['id']
                break
        
        if not calendar_id:
            error_msg = f"Calendar '{calendar_name}' not found!"
            logger.warn(error_msg)
            return {
                "statusCode": 404,
                "body": json.dumps({"error": error_msg})
            }
        
        # Get events from all sources
        start_time = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Get Google Calendar events
        google_events = get_google_calendar_events(
            service, calendar_id, start_time
        )
        logger.normal(
            f"\nFound {len(google_events)} events in Google Calendar "
            f"({calendar_name})"
        )
        
        # Get HipCamp events
        hipcamp_events = fetch_hipcamp_events(hipcamp_urls)
        logger.normal(f"Found {len(hipcamp_events)} events in HipCamp")
        
        # Get Checkfront events
        checkfront_events = fetch_checkfront_events(checkfront_url)
        logger.normal(f"Found {len(checkfront_events)} events in Checkfront")
        
        # Sync events to Google Calendar
        sync_events_to_calendar(
            service,
            calendar_id,
            hipcamp_events,
            checkfront_events,
            google_events,
            logger
        )
        
        # Clean up temporary files
        os.remove(credentials_path)
        if os.path.exists(token_path):
            os.remove(token_path)
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Calendar sync completed successfully",
                "events": {
                    "google": len(google_events),
                    "hipcamp": len(hipcamp_events),
                    "checkfront": len(checkfront_events)
                }
            })
        }
        
    except KeyError as e:
        error_msg = f"Missing required environment variable: {e}"
        logger.warn(error_msg)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": error_msg})
        }
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing JSON: {e}"
        logger.warn(error_msg)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": error_msg})
        }
    except Exception as e:
        error_msg = f"An error occurred: {e}"
        logger.warn(error_msg)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": error_msg})
        } 