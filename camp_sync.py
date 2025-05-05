"""
Camp Calendar Sync Script

This script synchronizes HipCamp reservations from multiple iCal feeds with a Google Calendar.
It fetches reservations from HipCamp's iCal feeds and creates/updates/deletes
corresponding events in a specified Google Calendar.

Features:
- Fetches events from multiple HipCamp iCal feeds
- Maps HipCamp sites to display names
- Syncs events to Google Calendar with metadata
- Handles event updates and deletions
- Maintains sync state using extended properties

Requirements:
- Google Calendar API credentials (credentials.json)
- Checkfront API credentials (checkfront_credentials.json)
- Python packages: google-auth-oauthlib, google-auth-httplib2, 
  google-api-python-client, requests, icalendar

Usage:
1. Set up Google Calendar API credentials
2. Copy checkfront_credentials.example.json to checkfront_credentials.json and fill in your credentials
3. Add HipCamp iCal URLs to the HIPCAMP_ICAL_URLS dictionary
4. Run the script: python camp_sync.py

Command line options:
  -v, --verbose    Enable warning level logging
  -vv, --debug     Enable debug level logging
"""

import datetime
import os.path
import re
import requests
import json
import hmac
import hashlib
import time
import base64
import argparse
from enum import Enum, auto
from typing import List, Optional, Dict, Union
from icalendar import Calendar, vDate

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.owned"
]

# Timezone for events
TIMEZONE = "America/New_York"  # EDT/EST timezone

# Map of HipCamp site names to display names
SITE_DISPLAY_NAMES = {
    "HillTop #1": "HT1",
    "HillTop #2": "HT2",
    "#1 Dropping In": "P1",
    "#2 Bunny Hop": "P2",
    "#3 Huck It!": "P3",
    "#4": "P4",
    "#5": "P5",
    "#6": "P6",
    "#7 Bike Escape": "P7",
    "#8 In The Zone": "P8",
    "#9 N_1": "P9",
    "#10 Missing Link": "P10"
}

# Map of HipCamp sites to Checkfront items
# Format: {
#   "HipCamp Site Name": {
#       "category_id": "Checkfront Category ID",
#       "item_id": "Checkfront Item ID"
#   }
# }
HIPCAMP_TO_CHECKFRONT = {
    "HillTop #1": {
        "category_id": "2",  # TODO: Add Checkfront category ID
        "item_id": "h1hilltop"       # TODO: Add Checkfront item ID
    },
    "HillTop #2": {
        "category_id": "2",
        "item_id": "h2hilltop"
    },
    "#1 Dropping In": {
        "category_id": "11",
        "item_id": "p1droppingin"
    },
    "#2 Bunny Hop": {
        "category_id": "11",
        "item_id": "p2bunnyhop"
    },
    "#3 Huck It!": {
        "category_id": "11",
        "item_id": "p3huckit"
    },
    "#4": {
        "category_id": "11",
        "item_id": "p4pedalersroost"
    },
    "#5": {
        "category_id": "11",
        "item_id": "p5cyclelife"
    },
    "#6": {
        "category_id": "11",
        "item_id": "p6comininhot"
    },
    "#7 Bike Escape": {
        "category_id": "11",
        "item_id": "p7bikeescape"
    },
    "#8 In The Zone": {
        "category_id": "11",
        "item_id": "p8inthezone"
    },
    "#9 N_1": {
        "category_id": "11",
        "item_id": "p9n1"
    },
    "#10 Missing Link": {
        "category_id": "11",
        "item_id": "p10missinglink"
    }
}

# Dictionary to store HipCamp iCal URLs
# Add your iCal URLs here
HIPCAMP_ICAL_URLS = {
    "HillTop #1": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48436&s=583082",  # Add URL
    "HillTop #2": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=68433&s=583083",  # Add URL
    "#1 Dropping In": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48461&s=607526",  # Add URL
    "#2 Bunny Hop": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48462&s=607527",  # Add URL
    "#3 Huck It!": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48463&s=643174",  # Add URL
    "#4": "",  # Add URL
    "#5": "",  # Add URL
    "#6": "",  # Add URL
    "#7 Bike Escape": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48464&s=643178",  # Add URL
    "#8 In The Zone": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48465&s=643179",  # Add URL
    "#9 N_1": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=48467&s=643180",  # Add URL
    "#10 Missing Link": "https://www.hipcamp.com/en-US/bookings/042e0cee-0952-4d18-9010-9b847e51446a/agenda.ics?cal=84802&s=643181"  # Add URL
}

# Checkfront iCal URL
CHECKFRONT_ICAL_URL = "https://dupont-bike-retreat.checkfront.com/view/bookings/ics/?id=9dadb199fc90cd1f3dd6427bf9c1eb3df155d4becdb2c55636be5d5b07e17ef4"

# Checkfront API configuration
CHECKFRONT_HOST = "dupont-bike-retreat.checkfront.com"

class LogLevel(Enum):
    """Logging levels for the script."""
    NORMAL = auto()
    WARN = auto()
    DEBUG = auto()


class Logger:
    """Simple logger with configurable levels."""
    
    def __init__(self, level: LogLevel = LogLevel.NORMAL):
        self.level = level
    
    def log(self, message: str, level: LogLevel = LogLevel.NORMAL) -> None:
        """
        Log a message if the current level is sufficient.
        
        Args:
            message: Message to log
            level: Level of the message
        """
        if level.value <= self.level.value:
            print(message)
    
    def normal(self, message: str) -> None:
        """Log a normal priority message."""
        self.log(message, LogLevel.NORMAL)
    
    def warn(self, message: str) -> None:
        """Log a warning priority message."""
        self.log(message, LogLevel.WARN)
    
    def debug(self, message: str) -> None:
        """Log a debug priority message."""
        self.log(message, LogLevel.DEBUG)


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


# Initialize logger with default level
logger = Logger(LogLevel.NORMAL)

def load_checkfront_credentials() -> tuple[str, str]:
    """
    Load Checkfront API credentials from the credentials file.
    
    Returns:
        Tuple of (api_key, api_secret)
        
    Raises:
        FileNotFoundError: If credentials file doesn't exist
        ValueError: If credentials file is invalid or missing required fields
    """
    credentials_path = "checkfront_credentials.json"
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Checkfront credentials file not found: {credentials_path}\n"
            "Please copy checkfront_credentials.example.json to checkfront_credentials.json "
            "and fill in your credentials."
        )
        
    try:
        with open(credentials_path) as f:
            credentials = json.load(f)
            
        api_key = credentials.get("api_key")
        api_secret = credentials.get("api_secret")
        
        if not api_key or not api_secret:
            raise ValueError(
                "Checkfront credentials file is missing required fields. "
                "Please ensure both api_key and api_secret are set."
            )
            
        return api_key, api_secret
        
    except json.JSONDecodeError:
        raise ValueError(
            "Invalid JSON in Checkfront credentials file. "
            "Please check the file format."
        )

# Load Checkfront credentials
CHECKFRONT_API_KEY, CHECKFRONT_API_SECRET = load_checkfront_credentials()

class CheckfrontAPI:
    """
    Client for interacting with the Checkfront API.
    
    Attributes:
        host: Checkfront hostname
        api_key: API key for authentication
        api_secret: API secret for authentication
    """
    
    def __init__(self, host: str, api_key: str, api_secret: str):
        self.host = host
        self.api_key = api_key
        self.api_secret = api_secret
    
    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict] = None
    ) -> Dict:
        """
        Make an authenticated request to the Checkfront API.
        
        Args:
            endpoint: API endpoint to call
            method: HTTP method (GET, POST, etc.)
            params: Optional query parameters
            
        Returns:
            API response as dictionary
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        # Create base64 encoded auth string
        auth_string = f"{self.api_key}:{self.api_secret}"
        auth_bytes = auth_string.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')

        headers = {
            "Authorization": f"Basic {base64_auth}",
            "Content-Type": "application/json"
        }
        
        url = f"https://{self.host}/api/3.0/{endpoint}"
        logger.debug(f"\nMaking {method} request to Checkfront API:")
        logger.debug(f"URL: {url}")
        logger.debug(f"Headers: {headers}")
        if params:
            logger.debug(f"Params: {json.dumps(params, indent=2)}")
            
        response = requests.request(
            method,
            url,
            headers=headers,
            json=params if method == "POST" else None,
            params=params if method != "POST" else None
        )
        
        logger.debug(f"Response Status Code: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        
        try:
            response_data = response.json()
            logger.debug(f"Response Body: {json.dumps(response_data, indent=2)}")
        except json.JSONDecodeError:
            logger.debug(f"Response Body (raw): {response.text}")
            
        response.raise_for_status()
        return response.json()
    
    def get_items(self) -> List[Dict]:
        """
        Get list of bookable items/sites.
        
        Returns:
            List of available items
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        response = self._make_request("item")
        return response.get("items", [])
    
    def get_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Get list of events from Checkfront.
        
        Args:
            start_date: Optional start date (YYYY-MM-DD)
            end_date: Optional end date (YYYY-MM-DD)
            
        Returns:
            List of events
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        response = self._make_request("event", params=params)
        return response.get("events", [])
    
    def get_hipcamp_event_mapping(self) -> Dict[str, str]:
        """
        Get a mapping of HipCamp booking IDs to Checkfront event IDs.
        The mapping is created by parsing the event names and notes.
        
        Returns:
            Dictionary mapping HipCamp booking IDs to Checkfront event IDs
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        # Get events for the next year
        now = datetime.datetime.now()
        end_date = (now + datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        events = self.get_events(end_date=end_date)
        
        # Create mapping of HipCamp booking IDs to Checkfront event IDs
        hipcamp_mapping = {}
        
        for event in events:
            # Look for HipCamp booking ID in notes
            notes = event.get("notes", "")
            match = re.search(r"HipCamp Booking ID: (\d+)", notes)
            if match:
                hipcamp_id = match.group(1)
                hipcamp_mapping[hipcamp_id] = event.get("event_id")
                logger.debug(
                    f"Found Checkfront event {event.get('event_id')} "
                    f"for HipCamp booking {hipcamp_id}"
                )
        
        return hipcamp_mapping
    
    def create_unavailable_event(
        self,
        start_date: str,
        end_date: str,
        name: str,
        category_id: str,
        item_id: str,
        notes: Optional[str] = None
    ) -> Dict:
        """
        Create an unavailable event in Checkfront.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            name: Event name
            category_id: Checkfront category ID
            item_id: Checkfront item ID
            notes: Optional event notes
            
        Returns:
            Created event details
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        logger.debug("\nCreating Checkfront unavailable event:")
        logger.debug(f"Name: {name}")
        logger.debug(f"Start Date: {start_date}")
        logger.debug(f"End Date: {end_date}")
        logger.debug(f"Category ID: {category_id}")
        logger.debug(f"Item ID: {item_id}")
        if notes:
            logger.debug(f"Notes: {notes}")
            
        data = {
            "start_date": start_date,
            "end_date": end_date,
            "name": f"{name} - Unavailable",
            "status": "U",  # U for unavailable
            "apply_to": {
                "category_id": category_id,
                "item_id": item_id
            }
        }
        
        if notes:
            data["notes"] = notes
            
        return self._make_request("event", method="POST", params=data)

# Create Checkfront API client
checkfront = CheckfrontAPI(
    CHECKFRONT_HOST,
    CHECKFRONT_API_KEY,
    CHECKFRONT_API_SECRET
)

def get_site_display_name(site_name: str) -> str:
    """
    Convert HipCamp site names to display names.
    
    Args:
        site_name: The site name from HipCamp
        
    Returns:
        Formatted display name for the site
    """
    return SITE_DISPLAY_NAMES.get(site_name, site_name)


def get_google_credentials(force_refresh: bool = False) -> Credentials:
    """
    Get Google Calendar API credentials, optionally forcing a refresh.
    
    Args:
        force_refresh: If True, forces new authentication even if token exists
        
    Returns:
        Credentials object for Google Calendar API
    """
    creds = None
    
    if not force_refresh and os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # If credentials don't exist or are invalid, get new ones
    if force_refresh or not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warn(f"Error refreshing token: {e}")
                logger.warn("Forcing new authentication...")
                creds = None
        
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
            
    return creds


class CalendarEvent:
    """
    Represents a calendar event from any source (Google Calendar or HipCamp).
    
    Attributes:
        start_time: Start time of the event
        end_time: End time of the event
        summary: Event title/summary
        description: Optional event description
        source: Source of the event (e.g., "hipcamp" or "google_calendar")
        source_id: ID of the event in its source system
        google_event_id: ID of the event in Google Calendar (if synced)
    """
    
    def __init__(
        self,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        summary: str,
        description: Optional[str] = None,
        source: str = "unknown",
        source_id: Optional[str] = None,
        google_event_id: Optional[str] = None,
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.summary = summary
        self.description = description
        self.source = source
        self.source_id = source_id
        self.google_event_id = google_event_id


def extract_booking_id(description: str) -> Optional[str]:
    """
    Extract the booking ID from the HipCamp event description.
    
    Args:
        description: The event description from HipCamp
        
    Returns:
        The booking ID if found, None otherwise
    """
    if not description:
        return None
        
    match = re.search(r"Booking ID: #(\d+)", description)
    if match:
        return match.group(1)
    return None


def fetch_hipcamp_events() -> List[CalendarEvent]:
    """
    Fetch events from all HipCamp iCal feeds and convert them to CalendarEvent objects.
    
    Returns:
        List of CalendarEvent objects
        
    Raises:
        requests.exceptions.RequestException: If any API request fails
    """
    all_events = []
    
    for site_name, url in HIPCAMP_ICAL_URLS.items():
        if not url:  # Skip if URL is not set
            continue
            
        try:
            response = requests.get(url)
            response.raise_for_status()
            
            # Parse the iCal data
            cal = Calendar.from_ical(response.text)
            
            for event in cal.walk("VEVENT"):
                # Get the booking ID from the description
                description = str(event.get("description", ""))
                booking_id = extract_booking_id(description)
                
                if not booking_id:
                    continue  # Skip events without booking IDs
                
                # Get dates
                start_date = event.get("dtstart").dt
                end_date = event.get("dtend").dt
                
                # Convert to datetime if they're date objects
                if isinstance(start_date, vDate):
                    start_time = datetime.datetime.combine(
                        start_date, datetime.time(14, 0)  # 2:00 PM check-in
                    )
                else:
                    start_time = start_date
                    
                if isinstance(end_date, vDate):
                    end_time = datetime.datetime.combine(
                        end_date, datetime.time(12, 0)  # 12:00 PM check-out
                    )
                else:
                    end_time = end_date
                
                # Get guest info from description and clean it up
                guest_info = description.split("\n")[0] if description else ""
                # Remove phone number if present
                guest_info = re.sub(r'\s*-\s*\+\d+.*$', '', guest_info)
                
                # Create the event
                display_name = get_site_display_name(site_name)
                event = CalendarEvent(
                    start_time=start_time,
                    end_time=end_time,
                    summary=f"{display_name} - {guest_info}",
                    description=description,
                    source="hipcamp",
                    source_id=booking_id
                )
                all_events.append(event)
                
        except requests.exceptions.RequestException as e:
            logger.warn(f"Error fetching events for {site_name}: {e}")
            continue
            
    return all_events


def get_google_calendar_events(
    service,
    calendar_id: str,
    start_time: datetime.datetime
) -> List[CalendarEvent]:
    """
    Fetch events from Google Calendar and convert them to CalendarEvent objects.
    
    Args:
        service: Google Calendar API service instance
        calendar_id: ID of the calendar to fetch events from
        start_time: Start time to fetch events from
        
    Returns:
        List of CalendarEvent objects
        
    Raises:
        HttpError: If the Google Calendar API request fails
    """
    try:
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_time.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        
        events = []
        for event in events_result.get("items", []):
            # Get the source ID from extended properties if it exists
            source = "google_calendar"
            source_id = None
            
            if "extendedProperties" in event:
                private_props = event["extendedProperties"].get("private", {})
                if "hipcamp_booking_id" in private_props:
                    source = "hipcamp"
                    source_id = private_props["hipcamp_booking_id"]
                elif "checkfront_booking_id" in private_props:
                    source = "checkfront"
                    source_id = private_props["checkfront_booking_id"]
            
            # Handle both all-day and timed events
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            
            # Convert to datetime, handling both date and datetime formats
            if "T" in start:  # This is a datetime
                start_time = datetime.datetime.fromisoformat(start)
            else:  # This is a date
                start_time = datetime.datetime.fromisoformat(f"{start}T00:00:00")
                
            if "T" in end:  # This is a datetime
                end_time = datetime.datetime.fromisoformat(end)
            else:  # This is a date
                end_time = datetime.datetime.fromisoformat(f"{end}T00:00:00")
            
            calendar_event = CalendarEvent(
                start_time=start_time,
                end_time=end_time,
                summary=event["summary"],
                description=event.get("description"),
                source=source,
                source_id=source_id,
                google_event_id=event["id"]
            )
            events.append(calendar_event)
            
        return events
        
    except HttpError as error:
        logger.warn(f"An error occurred: {error}")
        return []


def extract_checkfront_booking_id(url: str) -> Optional[str]:
    """
    Extract the booking ID from the Checkfront event URL.
    
    Args:
        url: The event URL from Checkfront
        
    Returns:
        The booking ID if found, None otherwise
    """
    if not url:
        logger.warn("Error: Empty URL provided to extract_checkfront_booking_id")
        return None
        
    logger.debug(f"Processing Checkfront URL: {url}")
    match = re.search(r'/booking/([^/]+)$', url)
    if match:
        booking_id = match.group(1)
        logger.debug(f"Found Checkfront booking ID: {booking_id}")
        return booking_id
    
    logger.warn(f"Error: Could not extract booking ID from URL: {url}")
    return None


def fetch_checkfront_events() -> List[CalendarEvent]:
    """
    Fetch events from Checkfront iCal feed and convert them to CalendarEvent objects.
    
    Returns:
        List of CalendarEvent objects
        
    Raises:
        requests.exceptions.RequestException: If the API request fails
    """
    all_events = []
    
    try:
        response = requests.get(CHECKFRONT_ICAL_URL)
        response.raise_for_status()
        
        # Parse the iCal data
        cal = Calendar.from_ical(response.text)
        
        for event in cal.walk("VEVENT"):
            # Get the booking ID from the URL
            url = str(event.get("url", ""))
            booking_id = extract_checkfront_booking_id(url)
            
            if not booking_id:
                continue  # Skip events without booking IDs
            
            # Get dates
            start_date = event.get("dtstart").dt
            end_date = event.get("dtend").dt
            
            # Convert to datetime if they're date objects
            if isinstance(start_date, vDate):
                start_time = datetime.datetime.combine(
                    start_date, datetime.time(14, 0)  # 2:00 PM check-in
                )
            else:
                start_time = start_date
                
            if isinstance(end_date, vDate):
                end_time = datetime.datetime.combine(
                    end_date, datetime.time(12, 0)  # 12:00 PM check-out
                )
            else:
                end_time = end_date
            
            # Get guest info and location
            guest_info = str(event.get("summary", ""))
            location = str(event.get("location", ""))
            
            # Clean up location name to match HipCamp format
            # Extract just the site code (e.g., "HT2" from "HT2 - HillTop Site#2")
            location = location.split("- ")[0].strip()
            
            # Create the event
            event = CalendarEvent(
                start_time=start_time,
                end_time=end_time,
                summary=f"{location} - {guest_info}",
                description=str(event.get("description", "")),
                source="checkfront",
                source_id=booking_id
            )
            all_events.append(event)
            
    except requests.exceptions.RequestException as e:
        logger.warn(f"Error fetching events from Checkfront: {e}")
        
    return all_events


def create_checkfront_event(event: CalendarEvent) -> Optional[str]:
    """
    Create an unavailable event in Checkfront for a HipCamp event.
    
    Args:
        event: HipCamp calendar event
        
    Returns:
        Checkfront event ID if successful, None otherwise
    """
    try:
        # Get the HipCamp site name from the event summary
        # Format: "HT1 - John Smith"
        site_display_name = event.summary.split(" - ", 1)[0]
        
        # Find the original HipCamp site name
        hipcamp_site_name = None
        for site, display_name in SITE_DISPLAY_NAMES.items():
            if display_name == site_display_name:
                hipcamp_site_name = site
                break
        
        if not hipcamp_site_name:
            logger.warn(
                f"Could not find HipCamp site for display name: "
                f"{site_display_name}"
            )
            return None
        
        # Get Checkfront mapping
        cf_mapping = HIPCAMP_TO_CHECKFRONT.get(hipcamp_site_name)
        if not cf_mapping:
            logger.warn(
                f"No Checkfront mapping found for HipCamp site: "
                f"{hipcamp_site_name}"
            )
            return None
        
        logger.debug(
            f"Creating Checkfront unavailable event for {site_display_name} "
            f"(HipCamp ID: {event.source_id})"
        )
        
        # Create unavailable event in Checkfront
        cf_event = checkfront.create_unavailable_event(
            start_date=event.start_time.strftime("%Y-%m-%d"),
            end_date=event.end_time.strftime("%Y-%m-%d"),
            name=site_display_name,
            category_id=cf_mapping["category_id"],
            item_id=cf_mapping["item_id"],
            notes=f"HipCamp Booking ID: {event.source_id}"
        )
        
        event_id = cf_event.get("event_id")
        if event_id:
            logger.debug(
                f"Created Checkfront event {event_id} for {site_display_name} "
                f"(HipCamp ID: {event.source_id})"
            )
        return event_id
        
    except Exception as e:
        logger.warn(f"Error creating Checkfront event: {e}")
        return None


def normalize_datetime(
    dt: Union[datetime.datetime, datetime.date]
) -> datetime.datetime:
    """
    Convert a date or datetime to a timezone-aware datetime.
    
    Args:
        dt: Date or datetime object to normalize
        
    Returns:
        Timezone-aware datetime object
    """
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        # Convert date to datetime at midnight UTC
        dt = datetime.datetime.combine(dt, datetime.time(0, 0))
    
    if dt.tzinfo is None:
        # Add UTC timezone if no timezone is set
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        
    return dt


def sync_events_to_calendar(
    service,
    calendar_id: str,
    hipcamp_events: List[CalendarEvent],
    checkfront_events: List[CalendarEvent],
    existing_events: List[CalendarEvent]
) -> None:
    """
    Sync HipCamp and Checkfront events to Google Calendar.
    
    This function:
    1. Creates new events for new reservations
    2. Updates existing events if they've changed
    3. Deletes events that no longer exist in either source
    4. Creates Checkfront unavailable events for new HipCamp events
    
    Args:
        service: Google Calendar API service instance
        calendar_id: ID of the calendar to sync events to
        hipcamp_events: List of current HipCamp events
        checkfront_events: List of current Checkfront events
        existing_events: List of existing Google Calendar events
        
    Raises:
        HttpError: If any Google Calendar API operation fails
    """
    # Get current time in UTC
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Get mapping of HipCamp events to Checkfront events
    hipcamp_to_checkfront = checkfront.get_hipcamp_event_mapping()
    
    # Create a map of existing events by source and ID
    existing_events_map: Dict[tuple, CalendarEvent] = {}
    # Maps (source, id) to Google Calendar ID
    google_event_ids: Dict[tuple, str] = {}
    
    for event in existing_events:
        if event.source_id:
            key = (event.source, event.source_id)
            existing_events_map[key] = event
            if event.google_event_id:
                google_event_ids[key] = event.google_event_id
                # Log existing event IDs for debugging
                if event.source == "hipcamp":
                    cf_id = None
                    if "extendedProperties" in event.__dict__:
                        private_props = (
                            event.extendedProperties.get("private", {})
                        )
                        cf_id = private_props.get("checkfront_event_id")
                    logger.debug(
                        f"Existing HipCamp event - ID: {event.source_id}, "
                        f"Checkfront ID: {cf_id}"
                    )
                elif event.source == "checkfront":
                    logger.debug(f"Existing Checkfront event - ID: {event.source_id}")
    
    # Create maps of new events by source and ID
    new_hipcamp_events = {
        ("hipcamp", event.source_id): event
        for event in hipcamp_events
        if event.source_id and normalize_datetime(event.end_time) > now
    }
    
    new_checkfront_events = {
        ("checkfront", event.source_id): event
        for event in checkfront_events
        if event.source_id and normalize_datetime(event.end_time) > now
    }
    
    # Combine all new events
    new_events = {**new_hipcamp_events, **new_checkfront_events}
    
    # Delete events that no longer exist in either source
    for key, event in existing_events_map.items():
        if key not in new_events:
            try:
                google_event_id = google_event_ids.get(key)
                if google_event_id:
                    service.events().delete(
                        calendarId=calendar_id,
                        eventId=google_event_id
                    ).execute()
                    if event.source == "hipcamp":
                        logger.normal(
                            f"Deleted HipCamp event: {event.summary} "
                            f"(ID: {event.source_id})"
                        )
                    else:
                        logger.normal(
                            f"Deleted Checkfront event: {event.summary} "
                            f"(ID: {event.source_id})"
                        )
            except HttpError as error:
                if "insufficientPermissions" in str(error):
                    logger.warn(
                        "Error: Insufficient permissions to delete events. "
                        "Please check your Google Calendar API scopes and "
                        "ensure you have write access to the calendar."
                    )
                else:
                    logger.warn(f"Error deleting event: {error}")
    
    # Create or update events
    for key, event in new_events.items():
        source, source_id = key
        
        # Skip events that have already ended
        if normalize_datetime(event.end_time) <= now:
            logger.debug(
                f"Skipping past event: {event.summary} "
                f"(ended: {event.end_time})"
            )
            continue
        
        # Format dates for all-day events (YYYY-MM-DD)
        start_date = event.start_time.strftime("%Y-%m-%d")
        end_date = event.end_time.strftime("%Y-%m-%d")
        
        # Add source to summary if not already present
        summary = event.summary
        if not summary.endswith(f" {source.capitalize()}"):
            summary = f"{summary} {source.capitalize()}"
        
        google_event = {
            "summary": summary,
            "description": event.description,
            "start": {
                "date": start_date,
                "timeZone": TIMEZONE,
            },
            "end": {
                "date": end_date,
                "timeZone": TIMEZONE,
            },
            "extendedProperties": {
                "private": {
                    f"{source}_booking_id": source_id,
                    "synced_by_script": "true"
                }
            }
        }
        
        try:
            if key in existing_events_map:
                # Update existing event using Google Calendar event ID
                google_event_id = google_event_ids.get(key)
                if google_event_id:
                    service.events().update(
                        calendarId=calendar_id,
                        eventId=google_event_id,
                        body=google_event
                    ).execute()
                    if source == "hipcamp":
                        logger.normal(
                            f"Updated HipCamp event: {summary} "
                            f"(ID: {source_id})"
                        )
                        # Check if we need to create/update Checkfront event
                        if source_id not in hipcamp_to_checkfront:
                            checkfront_id = create_checkfront_event(event)
                            if checkfront_id:
                                logger.debug(
                                    f"Created Checkfront unavailable event: "
                                    f"{checkfront_id} for HipCamp booking "
                                    f"{source_id}"
                                )
                                # Update the event with the Checkfront event ID
                                google_event["extendedProperties"][
                                    "private"
                                ]["checkfront_event_id"] = checkfront_id
                                service.events().update(
                                    calendarId=calendar_id,
                                    eventId=google_event_id,
                                    body=google_event
                                ).execute()
                                logger.debug(
                                    f"Linked HipCamp booking {source_id} "
                                    f"with Checkfront event {checkfront_id}"
                                )
                    else:
                        logger.normal(
                            f"Updated Checkfront event: {summary} "
                            f"(ID: {source_id})"
                        )
            else:
                # Create new event
                created_event = service.events().insert(
                    calendarId=calendar_id,
                    body=google_event
                ).execute()
                if source == "hipcamp":
                    logger.normal(
                        f"Created HipCamp event: {summary} "
                        f"(ID: {source_id})"
                    )
                    # Create Checkfront unavailable event for new HipCamp event
                    checkfront_id = create_checkfront_event(event)
                    if checkfront_id:
                        logger.normal(
                            f"Created Checkfront unavailable event: "
                            f"{checkfront_id} for HipCamp booking {source_id}"
                        )
                        # Update the event with the Checkfront event ID
                        google_event["extendedProperties"][
                            "private"
                        ]["checkfront_event_id"] = checkfront_id
                        service.events().update(
                            calendarId=calendar_id,
                            eventId=created_event["id"],
                            body=google_event
                        ).execute()
                        logger.debug(
                            f"Linked HipCamp booking {source_id} "
                            f"with Checkfront event {checkfront_id}"
                        )
                else:
                    logger.normal(
                        f"Created Checkfront event: {summary} "
                        f"(ID: {source_id})"
                    )
                # Store the Google Calendar ID for future updates
                google_event_ids[key] = created_event["id"]
                        
        except HttpError as error:
            if "insufficientPermissions" in str(error):
                logger.warn(
                    "Error: Insufficient permissions to modify events. "
                    "Please check your Google Calendar API scopes and "
                    "ensure you have write access to the calendar."
                )
            else:
                logger.warn(f"Error syncing event: {error}")


def main():
    """
    Main function that orchestrates the calendar sync process.
    
    This function:
    1. Authenticates with Google Calendar API
    2. Finds the target calendar
    3. Fetches events from Google Calendar, HipCamp, and Checkfront
    4. Syncs the events
    
    The script requires:
    - Google Calendar API credentials (credentials.json)
    - Checkfront API credentials (checkfront_credentials.json)
    - HipCamp iCal URLs in the HIPCAMP_ICAL_URLS dictionary
    - Checkfront iCal URL in CHECKFRONT_ICAL_URL
    """
    # Parse command line arguments
    args = parse_args()
    global logger
    logger = Logger(get_log_level(args.verbose))
    
    # Get credentials without forcing refresh
    creds = get_google_credentials(force_refresh=False)

    try:
        service = build("calendar", "v3", credentials=creds)

        # First, list all calendars to find the DBR Camping calendar
        logger.normal("Listing all calendars...")
        calendar_list = service.calendarList().list().execute()
        dbr_calendar_id = None
        
        for calendar in calendar_list.get('items', []):
            logger.debug(f"Calendar: {calendar['summary']} (ID: {calendar['id']})")
            if calendar['summary'] == "DBR Camping":
                dbr_calendar_id = calendar['id']
                break
        
        if not dbr_calendar_id:
            logger.warn("DBR Camping calendar not found!")
            return

        # Get events from all sources
        start_time = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Get Google Calendar events
        google_events = get_google_calendar_events(
            service, dbr_calendar_id, start_time
        )
        logger.normal(
            f"\nFound {len(google_events)} events in Google Calendar "
            f"(DBR Camping)"
        )
        
        # Get HipCamp events
        hipcamp_events = fetch_hipcamp_events()
        logger.normal(f"Found {len(hipcamp_events)} events in HipCamp")
        
        # Get Checkfront events
        checkfront_events = fetch_checkfront_events()
        logger.normal(f"Found {len(checkfront_events)} events in Checkfront")
        
        # Sync events to Google Calendar
        sync_events_to_calendar(
            service,
            dbr_calendar_id,
            hipcamp_events,
            checkfront_events,
            google_events
        )

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
