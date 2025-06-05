"""
Core functionality for Camp Calendar Sync.

This module contains the main classes and functions for synchronizing
HipCamp and Checkfront reservations with Google Calendar.
"""

import datetime
import os.path
import re
import requests
import json
import base64
from enum import Enum, auto
from typing import List, Optional, Dict, Union, Any

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
HIPCAMP_TO_CHECKFRONT = {
    "HillTop #1": {
        "category_id": "2",
        "item_id": "h1hilltop"
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
        print(f"\nMaking {method} request to Checkfront API:")
        print(f"URL: {url}")
        print(f"Headers: {headers}")
        if params:
            print(f"Params: {json.dumps(params, indent=2)}")
            
        response = requests.request(
            method,
            url,
            headers=headers,
            json=params if method == "POST" else None,
            params=params if method != "POST" else None
        )
        
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        try:
            response_data = response.json()
            print(f"Response Body: {json.dumps(response_data, indent=2)}")
        except json.JSONDecodeError:
            print(f"Response Body (raw): {response.text}")
            
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
                print(
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
        print("\nCreating Checkfront unavailable event:")
        print(f"Name: {name}")
        print(f"Start Date: {start_date}")
        print(f"End Date: {end_date}")
        print(f"Category ID: {category_id}")
        print(f"Item ID: {item_id}")
        if notes:
            print(f"Notes: {notes}")
            
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


def get_google_credentials(
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    force_refresh: bool = False
) -> Credentials:
    """
    Get Google Calendar API credentials, optionally forcing a refresh.
    
    Args:
        credentials_path: Path to the credentials.json file
        token_path: Path to store/load the token.json file
        force_refresh: If True, forces new authentication even if token exists
        
    Returns:
        Credentials object for Google Calendar API
    """
    creds = None
    
    if not force_refresh and os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # If credentials don't exist or are invalid, get new ones
    if force_refresh or not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                print("Forcing new authentication...")
                creds = None
        
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())
            
    return creds


def get_site_display_name(site_name: str) -> str:
    """
    Convert HipCamp site names to display names.
    
    Args:
        site_name: The site name from HipCamp
        
    Returns:
        Formatted display name for the site
    """
    return SITE_DISPLAY_NAMES.get(site_name, site_name)


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


def fetch_hipcamp_events(ical_urls: Dict[str, str]) -> List[CalendarEvent]:
    """
    Fetch events from all HipCamp iCal feeds and convert them to CalendarEvent objects.
    
    Args:
        ical_urls: Dictionary mapping site names to their iCal URLs
        
    Returns:
        List of CalendarEvent objects
        
    Raises:
        requests.exceptions.RequestException: If any API request fails
    """
    all_events = []
    
    for site_name, url in ical_urls.items():
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
            print(f"Error fetching events for {site_name}: {e}")
            continue
            
    return all_events


def get_google_calendar_events(
    service: Any,
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
        print(f"An error occurred: {error}")
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
        print("Error: Empty URL provided to extract_checkfront_booking_id")
        return None
        
    match = re.search(r'/booking/([^/]+)$', url)
    if match:
        booking_id = match.group(1)
        return booking_id
    
    print(f"Error: Could not extract booking ID from URL: {url}")
    return None


def fetch_checkfront_events(ical_url: str) -> List[CalendarEvent]:
    """
    Fetch events from Checkfront iCal feed and convert them to CalendarEvent objects.
    
    Args:
        ical_url: URL of the Checkfront iCal feed
        
    Returns:
        List of CalendarEvent objects
        
    Raises:
        requests.exceptions.RequestException: If the API request fails
    """
    all_events = []
    
    try:
        response = requests.get(ical_url)
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
        print(f"Error fetching events from Checkfront: {e}")
        
    return all_events


def sync_events_to_calendar(
    service: Any,
    calendar_id: str,
    hipcamp_events: List[CalendarEvent],
    checkfront_events: List[CalendarEvent],
    existing_events: List[CalendarEvent],
    logger: Optional[Logger] = None
) -> None:
    """
    Sync HipCamp and Checkfront events to Google Calendar.
    
    This function:
    1. Creates new events for new reservations
    2. Updates existing events if they've changed
    3. Deletes events that no longer exist in either source
    
    Args:
        service: Google Calendar API service instance
        calendar_id: ID of the calendar to sync events to
        hipcamp_events: List of current HipCamp events
        checkfront_events: List of current Checkfront events
        existing_events: List of existing Google Calendar events
        logger: Optional logger instance for output
        
    Raises:
        HttpError: If any Google Calendar API operation fails
    """
    if logger is None:
        logger = Logger()
        
    # Get current time in UTC
    now = datetime.datetime.now(datetime.timezone.utc)
    
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
    
    # Create maps of new events by source and ID
    new_hipcamp_events = {
        ("hipcamp", event.source_id): event
        for event in hipcamp_events
        if event.source_id and event.end_time > now
    }
    
    new_checkfront_events = {
        ("checkfront", event.source_id): event
        for event in checkfront_events
        if event.source_id and event.end_time > now
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
                    logger.normal(
                        f"Deleted {event.source} event: {event.summary} "
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
        if event.end_time <= now:
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
                    logger.normal(
                        f"Updated {source} event: {summary} "
                        f"(ID: {source_id})"
                    )
            else:
                # Create new event
                created_event = service.events().insert(
                    calendarId=calendar_id,
                    body=google_event
                ).execute()
                logger.normal(
                    f"Created {source} event: {summary} "
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