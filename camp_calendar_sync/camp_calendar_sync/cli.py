"""
Command-line interface for Camp Calendar Sync.

This module provides the command-line interface for synchronizing
HipCamp and Checkfront reservations with Google Calendar.
"""

import argparse
import datetime
import json
import os.path
from typing import Dict

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


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Sync HipCamp and Checkfront events to Google Calendar"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (use -v for warnings, -vv for debug)"
    )
    parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to Google Calendar API credentials file"
    )
    parser.add_argument(
        "--token",
        default="token.json",
        help="Path to store/load Google Calendar API token"
    )
    parser.add_argument(
        "--hipcamp-urls",
        default="hipcamp_urls.json",
        help="Path to JSON file containing HipCamp iCal URLs"
    )
    parser.add_argument(
        "--checkfront-url",
        default="checkfront_url.txt",
        help="Path to file containing Checkfront iCal URL"
    )
    parser.add_argument(
        "--calendar-name",
        default="DBR Camping",
        help="Name of the Google Calendar to sync to"
    )
    return parser.parse_args()


def get_log_level(verbose_count: int) -> LogLevel:
    """
    Convert verbose count to log level.
    
    Args:
        verbose_count: Number of -v flags
        
    Returns:
        Appropriate log level
    """
    if verbose_count >= 2:
        return LogLevel.DEBUG
    elif verbose_count == 1:
        return LogLevel.WARN
    return LogLevel.NORMAL


def load_hipcamp_urls(path: str) -> Dict[str, str]:
    """
    Load HipCamp iCal URLs from a JSON file.
    
    Args:
        path: Path to the JSON file
        
    Returns:
        Dictionary mapping site names to iCal URLs
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"HipCamp URLs file not found: {path}\n"
            "Please create a JSON file with site names and iCal URLs."
        )
        
    with open(path) as f:
        return json.load(f)


def load_checkfront_url(path: str) -> str:
    """
    Load Checkfront iCal URL from a file.
    
    Args:
        path: Path to the file
        
    Returns:
        Checkfront iCal URL
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Checkfront URL file not found: {path}\n"
            "Please create a file containing the Checkfront iCal URL."
        )
        
    with open(path) as f:
        return f.read().strip()


def main() -> None:
    """
    Main entry point for the CLI.
    
    This function:
    1. Parses command line arguments
    2. Sets up logging
    3. Loads configuration
    4. Authenticates with Google Calendar API
    5. Finds the target calendar
    6. Fetches events from all sources
    7. Syncs the events
    """
    # Parse command line arguments
    args = parse_args()
    logger = Logger(get_log_level(args.verbose))
    
    try:
        # Load configuration
        hipcamp_urls = load_hipcamp_urls(args.hipcamp_urls)
        checkfront_url = load_checkfront_url(args.checkfront_url)
        
        # Get credentials without forcing refresh
        creds = get_google_credentials(
            credentials_path=args.credentials,
            token_path=args.token,
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
            if calendar['summary'] == args.calendar_name:
                calendar_id = calendar['id']
                break
        
        if not calendar_id:
            logger.warn(f"Calendar '{args.calendar_name}' not found!")
            return
        
        # Get events from all sources
        start_time = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Get Google Calendar events
        google_events = get_google_calendar_events(
            service, calendar_id, start_time
        )
        logger.normal(
            f"\nFound {len(google_events)} events in Google Calendar "
            f"({args.calendar_name})"
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
        
    except FileNotFoundError as e:
        logger.warn(str(e))
    except json.JSONDecodeError as e:
        logger.warn(f"Error parsing JSON file: {e}")
    except HttpError as error:
        if "insufficientPermissions" in str(error):
            logger.warn(
                "Error: Insufficient permissions to access Google Calendar. "
                "Please check your Google Calendar API scopes and "
                "ensure you have the necessary permissions."
            )
        else:
            logger.warn(f"An error occurred: {error}")


if __name__ == "__main__":
    main() 