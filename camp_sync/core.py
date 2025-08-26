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
import base64
import argparse
from enum import Enum, auto
from typing import List, Optional, Dict, Union, Tuple
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

# These variables will be loaded from a configuration file.
SITE_DISPLAY_NAMES = {}
HIPCAMP_TO_CHECKFRONT = {}
HIPCAMP_ICAL_URLS = {}
CHECKFRONT_ICAL_URL = ""
CHECKFRONT_HOST = ""

# Number of days in the past to sync events from
SYNC_RANGE_DAYS = 90

# The API client will be initialized inside run_sync, once credentials are loaded.
checkfront = None

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


def format_event_date_for_logging(event) -> str:
    """
    Format event date information for logging messages.
    
    Args:
        event: Event object with start_time and end_time attributes
        
    Returns:
        Formatted date string for logging
    """
    try:
        if hasattr(event, 'start_time') and event.start_time:
            start_date = event.start_time.strftime("%Y-%m-%d")
            if hasattr(event, 'end_time') and event.end_time:
                end_date = event.end_time.strftime("%Y-%m-%d")
                if start_date == end_date:
                    return f"({start_date})"
                else:
                    return f"({start_date} to {end_date})"
            else:
                return f"({start_date})"
        else:
            return "(no date)"
    except Exception:
        return "(date error)"

def load_site_configuration():
    """
    Load site display names, Checkfront mappings, and iCal URLs from a JSON file.
    The path is specified by the SITE_CONFIG_PATH env variable,
    falling back to 'site_configuration.json' in the CWD.
    """
    global SITE_DISPLAY_NAMES, HIPCAMP_TO_CHECKFRONT, HIPCAMP_ICAL_URLS
    global CHECKFRONT_ICAL_URL, CHECKFRONT_HOST
    
    config_path_env = os.environ.get("SITE_CONFIG_PATH")
    config_path = config_path_env or "site_configuration.json"

    if not os.path.exists(config_path):
        logger.warn(
            f"WARN: Site configuration file not found at '{config_path}'. "
            "Using empty configs."
        )
        return

    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        SITE_DISPLAY_NAMES = config_data.get("SITE_DISPLAY_NAMES", {})
        HIPCAMP_TO_CHECKFRONT = config_data.get("HIPCAMP_TO_CHECKFRONT", {})
        HIPCAMP_ICAL_URLS = config_data.get("HIPCAMP_ICAL_URLS", {})
        CHECKFRONT_ICAL_URL = config_data.get("CHECKFRONT_ICAL_URL", "")
        CHECKFRONT_HOST = config_data.get("CHECKFRONT_HOST", "")
        
        logger.debug(
            f"Successfully loaded site configuration from {config_path}"
        )

    except json.JSONDecodeError:
        logger.warn(
            f"ERROR: Could not decode JSON from {config_path}. "
            "Using empty configs."
        )
    except Exception as e:
        logger.warn(
            f"ERROR: Failed to load site configuration: {e}. "
            "Using empty configs."
        )

def load_checkfront_credentials() -> Tuple[str, str]:
    """
    Load Checkfront API credentials from a JSON file.
    
    Returns:
        A tuple containing the API key and secret.
    """
    # Path to credentials file can be overridden by an environment variable.
    creds_path_env = os.environ.get("CHECKFRONT_CREDENTIALS_PATH")
    path = creds_path_env or "checkfront_credentials.json"
    
    logger.debug(f"Env var CHECKFRONT_CREDENTIALS_PATH: {creds_path_env}")
    logger.debug(f"Attempting to load Checkfront credentials from: {path}")

    with open(path, "r") as f:
        credentials = json.load(f)
    return credentials["api_key"], credentials["api_secret"]

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
        self.session = requests.Session()
        self.session.auth = (api_key, api_secret)
    
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
            logger.debug(f"Request Body: {json.dumps(params, indent=2)}")
            
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

    def create_booking_session(self) -> str:
        """
        Create a new booking session.
        
        Returns:
            Session ID for the new booking session
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
            ValueError: If no session ID is found in the response
        """
        logger.warn("Creating new Checkfront booking session...")
        response = self._make_request("booking/session", method="POST")
        # Session ID is nested in the response as booking.session.id
        session = response.get("booking", {}).get("session", {})
        self._session_id = session.get("id")
        if not self._session_id:
            error_msg = (
                "No session ID found in Checkfront API response. "
                f"Response: {json.dumps(response, indent=2)}"
            )
            logger.normal(f"Failed to create booking session: {error_msg}")
            raise ValueError(error_msg)
        logger.warn(f"Created booking session: {self._session_id}")
        return self._session_id
    
    def add_item_to_session(
        self,
        item_id: str,
        start_date: str,
        end_date: str,
        quantity: int = 1,
        params: Optional[Dict] = None
    ) -> Dict:
        """
        Add an item to the current booking session.
        
        Args:
            item_id: Checkfront item ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            quantity: Number of items to book
            params: Optional additional parameters
            
        Returns:
            Session details with added item
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
            ValueError: If no active session exists, if no SLIP is returned,
                      or if the item is unavailable/overbooked
        """
        if not self._session_id:
            error_msg = "No active booking session"
            logger.warn(f"Failed to add item to session: {error_msg}")
            raise ValueError(error_msg)
            
        # Convert dates to Checkfront format (YYYYMMDD)
        cf_start_date = start_date.replace("-", "")
        cf_end_date = end_date.replace("-", "")
            
        # Get rated item details first
        item_params = {
            "start_date": cf_start_date,
            "end_date": cf_end_date,
            "param": {
                "qty": str(quantity)
            }
        }
        if params:
            item_params["param"].update(params)
            
        logger.warn(
            f"Getting availability for {item_id} "
            f"({start_date} to {end_date})"
        )
        
        # Get rated item details to get the SLIP
        rated_item = self._make_request(
            f"item/{item_id}",
            params=item_params
        )
        
        # Check rate status and availability
        rate = rated_item.get("item", {}).get("rate", {})
        status = rate.get("status")
        
        if status == "ERROR":
            error = rate.get("error", {})
            error_id = error.get("id")
            error_title = error.get("title", "Unknown error")
            error_msg = (
                f"Item {item_id} is unavailable: {error_title} "
                f"(Error ID: {error_id})"
            )
            logger.warn(f"Failed to add item to session: {error_msg}")
            if logger.level == LogLevel.DEBUG:
                raise ValueError(
                    f"{error_msg}. Response: {json.dumps(rated_item, indent=2)}"
                )
            else:
                raise ValueError(error_msg)
        elif status != "AVAILABLE":
            error_msg = f"Item {item_id} has unexpected status: {status}"
            logger.warn(f"Failed to add item to session: {error_msg}")
            if logger.level == LogLevel.DEBUG:
                raise ValueError(
                    f"{error_msg}. Response: {json.dumps(rated_item, indent=2)}"
                )
            else:
                raise ValueError(error_msg)
            
        # Extract the SLIP from the rated response
        slip = rate.get("slip")
        if not slip:
            error_msg = f"No SLIP returned for item {item_id}"
            logger.warn(f"Failed to add item to session: {error_msg}")
            if logger.level == LogLevel.DEBUG:
                raise ValueError(
                    f"{error_msg}. Response: {json.dumps(rated_item, indent=2)}"
                )
            else:
                raise ValueError(error_msg)
            
        logger.warn(f"Got SLIP for item {item_id}: {slip}")
        logger.warn(f"Adding item {item_id} to booking session...")
            
        # Add item to session using SLIP
        session_params = {
            "session_id": self._session_id,
            "slip": slip
        }
        
        response = self._make_request(
            "booking/session",
            method="POST",
            params=session_params
        )
        
        # Verify the item was added to the session
        session = response.get("booking", {}).get("session", {})
        items = session.get("item", [])
        
        if not items:
            error_msg = f"Failed to add item {item_id} to session - no items in session"
            logger.warn(f"Failed to add item to session: {error_msg}")
            if logger.level == LogLevel.WARN:
                raise ValueError(
                    f"{error_msg}. Response: {json.dumps(response, indent=2)}"
                )
            else:
                raise ValueError(error_msg)

        # Log session details in debug mode
        if logger.level == LogLevel.DEBUG:
            logger.debug(
                f"Session details after adding item:\n"
                f"Session ID: {session.get('id')}\n"
                f"Items: {json.dumps(items, indent=2)}\n"
                f"Total: {session.get('total')}"
            )
            
        logger.warn(f"Successfully added item {item_id} to booking session")
        return response
    
    def create_booking(
        self,
        customer_info: Dict[str, str],
        notes: Optional[str] = None
    ) -> Dict:
        """
        Create a booking from the current session.
        
        Args:
            customer_info: Dictionary of customer information
            notes: Optional booking notes
            
        Returns:
            Created booking details
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
            ValueError: If no active session exists or if the booking creation fails
        """
        if not self._session_id:
            error_msg = "No active booking session"
            logger.normal(f"Failed to create booking: {error_msg}")
            raise ValueError(error_msg)
            
        logger.warn("Getting required booking form fields...")
        # Get booking form fields
        form_response = self._make_request("booking/form")
        form_fields = form_response.get("booking_form_ui", {})
        
        # Find required fields by checking customer.required flag
        required_fields = []
        for field_name, field_data in form_fields.items():
            if not isinstance(field_data, dict):
                continue
                
            define = field_data.get("define", {})
            layout = define.get("layout", {})
            customer = layout.get("customer", {})
            
            # Check if field is required for customers
            if customer.get("required") == 1:
                field_label = layout.get("lbl", field_name)
                required_fields.append((field_name, field_label))
        
        logger.warn(f"Required fields: {json.dumps([f[1] for f in required_fields], indent=2)}")

        # Create default customer info with standard fields
        default_customer_info = {
            "customer_name": customer_info.get("name", "Guest"),
            "customer_email": customer_info.get("email", "guest@example.com"),
            "customer_phone": customer_info.get("phone", "555-555-5555"),
            # Add default values for camping-specific fields with exact field names from API
            "camping_setup": "No",
            "vehicle__trailer_camping": "No",
            "RV_details": "N/A",
            "trailer_details": "N/A"
        }
        
        # Merge provided customer info with defaults
        # Convert any provided field names to match Checkfront's format
        field_mapping = {
            "name": "customer_name",
            "email": "customer_email",
            "phone": "customer_phone",
            # Add mappings for camping fields using exact API field names
            "tent_camping": "camping_setup",
            "vehicle_trailer_camping": "vehicle__trailer_camping",
            "rv_details": "RV_details",
            "trailer_details": "trailer_details"
        }
        
        merged_customer_info = default_customer_info.copy()
        for key, value in customer_info.items():
            # Map common field names to Checkfront format
            checkfront_key = field_mapping.get(key, key)
            if value:  # Only update if value is not empty
                merged_customer_info[checkfront_key] = value

        # Validate required fields
        missing_fields = []
        for field_name, field_label in required_fields:
            if field_name not in merged_customer_info or not merged_customer_info[field_name]:
                missing_fields.append(field_label)
                
        if missing_fields:
            error_msg = (
                f"Missing required customer fields: {', '.join(missing_fields)}"
            )
            logger.normal(f"Failed to create booking: {error_msg}")
            raise ValueError(error_msg)
            
        # Create booking
        logger.warn("Creating booking with customer information...")
        
        # Ensure all values are JSON-serializable
        serializable_customer_info = {}
        for key, value in merged_customer_info.items():
            if isinstance(value, set):
                serializable_customer_info[key] = list(value)
            else:
                serializable_customer_info[key] = value
                
        logger.warn(f"Customer information: {json.dumps(serializable_customer_info, indent=2)}")
        
        # Format customer information as form parameters
        booking_data = {
            "session_id": self._session_id,
            "form": serializable_customer_info  # Send as a single object
        }
        
        if notes:
            booking_data["notes"] = notes
            
        logger.warn(f"Booking data: {json.dumps(booking_data, indent=2)}")
        
        response = self._make_request(
            "booking/create",
            method="POST",
            params=booking_data
        )
        
        # Check for errors in the response
        request_status = response.get("request", {}).get("status")
        if request_status == "ERROR":
            error = response.get("request", {}).get("error", {})
            error_id = error.get("id", "unknown_error")
            error_title = error.get("title", "Unknown error")
            error_details = error.get("details", "")
            error_msg = f"Booking creation failed: {error_title}"
            if error_details:
                error_msg += f" - {error_details}"
            logger.warn(f"Failed to create booking: {error_msg}")
            if logger.level == LogLevel.DEBUG:
                raise ValueError(
                    f"{error_msg} (Error ID: {error_id}). "
                    f"Response: {json.dumps(response, indent=2)}"
                )
            else:
                raise ValueError(error_msg)
                
        logger.normal("Successfully created booking")
        return response
    
    def create_hipcamp_booking(
        self,
        event: CalendarEvent,
        customer_info: Dict[str, str]
    ) -> Optional[str]:
        """
        Create a Checkfront booking for a HipCamp event.
        
        Args:
            event: HipCamp calendar event
            customer_info: Dictionary of customer information
            
        Returns:
            Checkfront booking ID if successful, None otherwise
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
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
                error_msg = f"Could not find HipCamp site for display name: {site_display_name}"
                logger.normal(f"Failed to create Checkfront booking: {error_msg}")
                return None
            
            # Get Checkfront mapping
            cf_mapping = HIPCAMP_TO_CHECKFRONT.get(hipcamp_site_name)
            if not cf_mapping:
                error_msg = f"No Checkfront mapping found for HipCamp site: {hipcamp_site_name}"
                logger.normal(f"Failed to create Checkfront booking: {error_msg}")
                return None
            
            date_info = format_event_date_for_logging(event)
            logger.normal(
                f"Creating Checkfront booking for {site_display_name} "
                f"(HipCamp ID: {event.source_id}) {date_info}"
            )
            
            # Create booking session
            self.create_booking_session()
            
            # Add item to session
            try:
                self.add_item_to_session(
                    item_id=cf_mapping["item_id"],
                    start_date=event.start_time.strftime("%Y-%m-%d"),
                    end_date=event.end_time.strftime("%Y-%m-%d")
                )
            except ValueError as availability_error:
                error_text = str(availability_error)
                # Treat SOLDOUT/OVERBOOK/unavailable as "already booked" and skip creating
                if (
                    "SOLDOUT" in error_text
                    or "OVERBOOK" in error_text
                    or "unavailable" in error_text
                ):
                    logger.normal(
                        f"Checkfront indicates dates are unavailable for {site_display_name} "
                        f"(HipCamp ID: {event.source_id}) {date_info}. Skipping booking creation."
                    )
                    return None
                # Otherwise, re-raise
                raise
            
            # Create booking with customer info and HipCamp reference
            booking = self.create_booking(
                customer_info=customer_info,
                notes=f"HipCamp Booking ID: {event.source_id}"
            )
            
            logger.warn(f"Full booking response: {json.dumps(booking, indent=2)}")
            
            # Try different possible fields for booking ID
            booking_id = (
                booking.get("booking", {}).get("id") or
                booking.get("booking_id") or 
                booking.get("id") or 
                booking.get("booking", {}).get("booking_id")
            )
            
            if booking_id:
                logger.normal(
                    f"Created Checkfront booking {booking_id} for {site_display_name} "
                    f"(HipCamp ID: {event.source_id}) {date_info}"
                )
            else:
                logger.normal(
                    f"Failed to create Checkfront booking for {site_display_name} "
                    f"(HipCamp ID: {event.source_id}): No booking ID in response. "
                    f"Response keys: {list(booking.keys())}"
                )
            return booking_id
            
        except Exception as e:
            logger.normal(f"Error creating Checkfront booking: {e}")
            return None
        finally:
            # Clear session ID
            self._session_id = None

    def delete_booking(self, booking_id: str) -> bool:
        """
        Delete a Checkfront booking.
        
        Args:
            booking_id: The ID of the booking to delete
            
        Returns:
            True if successfully deleted, False otherwise
            
        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        try:
            logger.normal(f"Deleting Checkfront booking: {booking_id}")
            
            response = self._make_request(
                endpoint=f"booking/{booking_id}",
                method="DELETE"
            )
            
            # Checkfront API typically returns success response for deletions
            logger.normal(f"Successfully deleted Checkfront booking: {booking_id}")
            return True
            
        except Exception as e:
            logger.normal(f"Error deleting Checkfront booking {booking_id}: {e}")
            return False

    def delete_hipcamp_booking(self, hipcamp_id: str) -> bool:
        """
        Delete a Checkfront booking that was created for a HipCamp reservation.
        
        Args:
            hipcamp_id: The HipCamp booking ID
            
        Returns:
            True if successfully deleted, False otherwise
        """
        try:
            # Get the mapping to find the Checkfront booking ID
            hipcamp_mapping = self.get_hipcamp_event_mapping()
            checkfront_booking_id = hipcamp_mapping.get(hipcamp_id)
            
            if not checkfront_booking_id:
                logger.debug(
                    f"No Checkfront booking found for HipCamp ID: {hipcamp_id}"
                )
                return False
            
            logger.normal(
                f"Found Checkfront booking {checkfront_booking_id} "
                f"for HipCamp booking {hipcamp_id}, deleting..."
            )
            
            return self.delete_booking(checkfront_booking_id)
            
        except Exception as e:
            logger.normal(
                f"Error deleting HipCamp booking {hipcamp_id}: {e}"
            )
            return False

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
    Get Google Calendar API credentials.
    Handles token refresh and initial authentication.
    
    Args:
        force_refresh: If True, force a re-authentication.
        
    Returns:
        Google Calendar API credentials
    """
    creds = None
    # Paths to credential files can be overridden by environment variables.
    token_path_env = os.environ.get("GOOGLE_TOKEN_PATH")
    creds_path_env = os.environ.get("GOOGLE_CREDENTIALS_PATH")
    
    token_path = token_path_env or "token.json"
    credentials_path = creds_path_env or "google_credentials.json"

    logger.debug(f"Env var GOOGLE_TOKEN_PATH: {token_path_env}")
    logger.debug(f"Using Google token path: {token_path}")
    logger.debug(f"Env var GOOGLE_CREDENTIALS_PATH: {creds_path_env}")
    logger.debug(f"Using Google credentials path: {credentials_path}")

    # The file token.json stores the user's access and refresh tokens
    if not force_refresh and os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
            
    return creds


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
    """
    all_events = []
    # Add cache-busting headers to ensure we get fresh data
    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }
    
    for site_name, url in HIPCAMP_ICAL_URLS.items():
        if not url:  # Skip if URL is not set
            continue
            
        try:
            response = requests.get(url, headers=headers)
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
            logger.normal(f"Error fetching events for {site_name}: {e}")
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
    """
    all_events = []
    
    # Debug: Log Checkfront iCal URL
    logger.debug(f"🔍 CHECKFRONT DEBUG: Fetching from URL: {CHECKFRONT_ICAL_URL}")
    
    # Add cache-busting headers to ensure we get fresh data
    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }
    
    try:
        response = requests.get(CHECKFRONT_ICAL_URL, headers=headers)
        response.raise_for_status()
        
        # Debug: Log response details
        logger.debug(f"🔍 CHECKFRONT DEBUG: Response status: {response.status_code}")
        logger.debug(f"🔍 CHECKFRONT DEBUG: Response size: {len(response.text)} characters")
        logger.debug(f"🔍 CHECKFRONT DEBUG: Response headers: {dict(response.headers)}")
        
        # Parse the iCal data
        cal = Calendar.from_ical(response.text)
        
        # Debug: Log calendar parsing
        logger.debug(f"🔍 CHECKFRONT DEBUG: Parsed calendar with {len(cal.walk('VEVENT'))} events")
        
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
            
            # Debug: Log event details being processed
            logger.debug(f"🔍 CHECKFRONT DEBUG: Processing event - Summary: '{guest_info}', Location: '{event.get('location', 'N/A')}', Booking ID: {booking_id}")
            
            # Skip events that were created from HipCamp bookings
            if "(HipCamp)" in guest_info:
                logger.debug(f"Skipping Checkfront event from HipCamp: {guest_info}")
                continue
                
            location = str(event.get("location", ""))
            
            # Clean up location name to match HipCamp format
            # Extract just the site code (e.g., "HT2" from "HT2 - HillTop Site#2")
            location = location.split("- ")[0].strip()
            
            # Debug: Log processed event
            logger.debug(f"🔍 CHECKFRONT DEBUG: Created event - Location: '{location}', Guest: '{guest_info}', Dates: {start_time} to {end_time}")
            
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
        logger.normal(f"Error fetching events from Checkfront: {e}")
    
    # Debug: Log final result
    logger.debug(f"🔍 CHECKFRONT DEBUG: Final result - {len(all_events)} events created")
    for i, event in enumerate(all_events[:3]):  # Show first 3 events
        logger.debug(f"🔍 CHECKFRONT DEBUG: Event {i+1}: {event.summary} (ID: {event.source_id})")
        
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


def _extract_customer_info_from_hipcamp_event(event: CalendarEvent) -> Dict[str, str]:
    """Extracts customer information from a HipCamp event description."""
    customer_info = {}
    if not event.description:
        return {}

    lines = event.description.split("\n")
    guest_info = lines[0]
    name = guest_info.split(" - ")[0].strip()
    # Append (HipCamp) to the name to identify these bookings
    customer_info["name"] = f"{name} (HipCamp)"

    # Try to find email in description
    email = None
    for line in lines:
        if "@" in line and "." in line:
            email = line.strip()
            break
    
    if email:
        customer_info["email"] = email
    else:
        # Create sanitized email from name
        sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', name.lower())
        customer_info["email"] = f"{sanitized_name}@example.com"
        
    return customer_info


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
    4. Creates Checkfront bookings for new HipCamp events
    
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
    
    # Debug: Log sync parameters
    logger.debug(f"🔍 SYNC DEBUG: Calendar ID: {calendar_id}")
    logger.debug(f"🔍 SYNC DEBUG: HipCamp events: {len(hipcamp_events)}")
    logger.debug(f"🔍 SYNC DEBUG: Checkfront events: {len(checkfront_events)}")
    logger.debug(f"🔍 SYNC DEBUG: Existing events: {len(existing_events)}")
    logger.debug(f"🔍 SYNC DEBUG: Current time: {now}")
    
    # Get mapping of HipCamp events to Checkfront events
    hipcamp_to_checkfront = checkfront.get_hipcamp_event_mapping()
    logger.debug(f"🔍 SYNC DEBUG: HipCamp to Checkfront mapping: {len(hipcamp_to_checkfront)} entries")
    
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
                        cf_id = (
                            private_props.get("checkfront_booking_id")
                            or private_props.get("checkfront_event_id")
                        )
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
    
    # Debug: Log event processing
    logger.debug(f"🔍 SYNC DEBUG: New HipCamp events: {len(new_hipcamp_events)}")
    logger.debug(f"🔍 SYNC DEBUG: New Checkfront events: {len(new_checkfront_events)}")
    logger.debug(f"🔍 SYNC DEBUG: Total new events: {len(new_events)}")
    
    # Debug: Show some event details
    for source, event_id in list(new_events.keys())[:3]:
        event = new_events[(source, event_id)]
        logger.debug(f"🔍 SYNC DEBUG: Processing {source} event - ID: {event_id}, Summary: '{event.summary}'")
    
    # Delete events that no longer exist in either source
    for key, event in existing_events_map.items():
        if key not in new_events:
            # Don't delete events that are already in the past
            if normalize_datetime(event.end_time) <= now:
                logger.debug(
                    f"Skipping deletion of past event: {event.summary} "
                    f"(ended {event.end_time})"
                )
                continue

            try:
                google_event_id = google_event_ids.get(key)
                if google_event_id:
                    service.events().delete(
                        calendarId=calendar_id,
                        eventId=google_event_id
                    ).execute()
                    if event.source == "hipcamp":
                        date_info = format_event_date_for_logging(event)
                        logger.normal(
                            f"Deleted HipCamp event: {event.summary} "
                            f"(ID: {event.source_id}) {date_info}"
                        )
                        # Also delete the associated Checkfront booking
                        if event.source_id and checkfront:
                            try:
                                checkfront.delete_hipcamp_booking(event.source_id)
                            except Exception as e:
                                logger.warn(
                                    f"Error deleting Checkfront booking for "
                                    f"HipCamp ID {event.source_id}: {e}"
                                )
                    else:
                        date_info = format_event_date_for_logging(event)
                        logger.normal(
                            f"Deleted Checkfront event: {event.summary} "
                            f"(ID: {event.source_id}) {date_info}"
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
                        # Get the original event to extract date info
                        original_event = None
                        for event_list in [hipcamp_events, checkfront_events]:
                            for evt in event_list:
                                if hasattr(evt, 'source_id') and evt.source_id == source_id:
                                    original_event = evt
                                    break
                            if original_event:
                                break
                        
                        date_info = format_event_date_for_logging(original_event) if original_event else ""
                        logger.normal(
                            f"Updated HipCamp event: {summary} "
                            f"(ID: {source_id}) {date_info}"
                        )
                        # Check if we need to create/update Checkfront booking
                        # Only create if this is a new HipCamp event that doesn't already have a Checkfront booking
                        logger.debug(f"🔍 SYNC DEBUG: Checking if HipCamp event {source_id} needs Checkfront booking")
                        logger.debug(f"🔍 SYNC DEBUG: Current mapping has {len(hipcamp_to_checkfront)} entries")
                        logger.debug(f"🔍 SYNC DEBUG: HipCamp ID {source_id} in mapping: {source_id in hipcamp_to_checkfront}")
                        
                        if source_id not in hipcamp_to_checkfront:
                            logger.debug(f"Creating new Checkfront booking for HipCamp event {source_id} (not found in existing mapping)")
                            # Extract customer info from event description
                            customer_info = _extract_customer_info_from_hipcamp_event(event)
                            
                            # Create Checkfront booking
                            checkfront_id = checkfront.create_hipcamp_booking(
                                event,
                                customer_info
                            )
                            if checkfront_id:
                                logger.normal(
                                    f"Created Checkfront booking: {checkfront_id} "
                                    f"for HipCamp booking {source_id} {date_info}"
                                )
                                # Update the event with the Checkfront booking ID
                                google_event["extendedProperties"][
                                    "private"
                                ]["checkfront_booking_id"] = checkfront_id
                                service.events().update(
                                    calendarId=calendar_id,
                                    eventId=google_event_id,
                                    body=google_event
                                ).execute()
                                logger.debug(
                                    f"Linked HipCamp booking {source_id} "
                                    f"with Checkfront booking {checkfront_id}"
                                )
                        else:
                            logger.debug(f"🔍 SYNC DEBUG: HipCamp event {source_id} already has Checkfront booking, skipping creation")
                    else:
                        # Get the original event to extract date info
                        original_event = None
                        for event_list in [hipcamp_events, checkfront_events]:
                            for evt in event_list:
                                if hasattr(evt, 'source_id') and evt.source_id == source_id:
                                    original_event = evt
                                    break
                            if original_event:
                                break
                        
                        date_info = format_event_date_for_logging(original_event) if original_event else ""
                        logger.normal(
                            f"Updated Checkfront event: {summary} "
                            f"(ID: {source_id}) {date_info}"
                        )
            else:
                # Create new event
                created_event = service.events().insert(
                    calendarId=calendar_id,
                    body=google_event
                ).execute()
                if source == "hipcamp":
                    date_info = format_event_date_for_logging(event)
                    logger.normal(
                        f"Created HipCamp event: {summary} "
                        f"(ID: {source_id}) {date_info}"
                    )
                    # Create Checkfront booking for new HipCamp event
                    # Extract customer info from event description
                    customer_info = _extract_customer_info_from_hipcamp_event(event)
                    
                    # Create Checkfront booking
                    checkfront_id = checkfront.create_hipcamp_booking(
                        event,
                        customer_info
                    )
                    if checkfront_id:
                        logger.normal(
                            f"Created Checkfront booking: {checkfront_id} "
                            f"for HipCamp booking {source_id} {date_info}"
                        )
                        # Update the event with the Checkfront booking ID
                        google_event["extendedProperties"][
                            "private"
                        ]["checkfront_booking_id"] = checkfront_id
                        service.events().update(
                            calendarId=calendar_id,
                            eventId=created_event["id"],
                            body=google_event
                        ).execute()
                        logger.debug(
                            f"Linked HipCamp booking {source_id} "
                            f"with Checkfront booking {checkfront_id}"
                        )
                else:
                    date_info = format_event_date_for_logging(event)
                    logger.normal(
                        f"Created Checkfront event: {summary} "
                        f"(ID: {source_id}) {date_info}"
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


def run_sync():
    """
    Main synchronization function.
    
    Initializes credentials, fetches events from all sources,
    and syncs them to the Google Calendar.
    """
    # Load all configurations first
    load_site_configuration()
    
    # The API client needs credentials to be loaded.
    global checkfront
    api_key, api_secret = load_checkfront_credentials()
    checkfront = CheckfrontAPI(
        CHECKFRONT_HOST,
        api_key,
        api_secret
    )
    
    # Get Google Calendar service
    logger.normal("Authenticating with Google Calendar...")
    service = build("calendar", "v3", credentials=get_google_credentials())
    
    # --- Main Logic ---
    # Get the ID of the main DBR Camping calendar
    dbr_calendar_id = None
    site_calendars = {}
    
    calendar_list = service.calendarList().list().execute()
    for calendar_list_entry in calendar_list["items"]:
        if calendar_list_entry["summary"] == "DBR Camping":
            dbr_calendar_id = calendar_list_entry["id"]
        # Check for site-specific calendars (e.g., "HT1 Checkfront")
        elif calendar_list_entry["summary"].endswith(" Checkfront"):
            site_code = calendar_list_entry["summary"].split(" ")[0]
            site_calendars[site_code] = calendar_list_entry["id"]
    
    if not dbr_calendar_id:
        logger.normal("Main 'DBR Camping' calendar not found.")
        return

    logger.normal(f"Found main calendar: DBR Camping (ID: {dbr_calendar_id})")
    logger.normal(f"Found {len(site_calendars)} site-specific calendars.")

    # Get existing events from Google Calendar
    now = datetime.datetime.now(datetime.timezone.utc)
    start_time = now - datetime.timedelta(days=SYNC_RANGE_DAYS)
    
    logger.normal("Fetching existing events from Google Calendar...")
    google_events = get_google_calendar_events(
        service, dbr_calendar_id, start_time
    )
    logger.normal(f"Found {len(google_events)} events in Google Calendar")
    
    # Get HipCamp events
    hipcamp_events = fetch_hipcamp_events()
    logger.normal(f"Found {len(hipcamp_events)} events in HipCamp")
    
    # Debug: Dump HipCamp events details
    logger.debug("🔍 HIPCAMP EVENTS DETAILS:")
    for i, event in enumerate(hipcamp_events[:3]):  # Show first 3 events
        logger.debug(f"   {i+1}. Summary: '{event.summary}'")
        logger.debug(f"      ID: {getattr(event, 'source_id', 'N/A')}")
        logger.debug(f"      Start: {getattr(event, 'start_time', 'N/A')}")
        logger.debug(f"      End: {getattr(event, 'end_time', 'N/A')}")
        logger.debug(f"      Description: '{getattr(event, 'description', 'N/A')[:100]}...'")
    
    # Get Checkfront events
    checkfront_events = fetch_checkfront_events()
    logger.normal(f"Found {len(checkfront_events)} events in Checkfront")
    
    # Debug: Dump Checkfront events details
    logger.debug("🔍 CHECKFRONT EVENTS DETAILS:")
    for i, event in enumerate(checkfront_events[:3]):  # Show first 3 events
        logger.debug(f"   {i+1}. Summary: '{event.summary}'")
        logger.debug(f"      ID: {getattr(event, 'source_id', 'N/A')}")
        logger.debug(f"      Start: {getattr(event, 'start_time', 'N/A')}")
        logger.debug(f"      End: {getattr(event, 'end_time', 'N/A')}")
        logger.debug(f"      Description: '{getattr(event, 'description', 'N/A')[:100]}...'")
    
    # Sync events to main Google Calendar
    sync_events_to_calendar(
        service,
        dbr_calendar_id,
        hipcamp_events,
        checkfront_events,
        google_events
    )
    
    # Sync Checkfront events to site-specific calendars
    for site_code, calendar_id in site_calendars.items():
        logger.normal(f"\nSyncing events to {site_code} Checkfront calendar...")
        
        # Get existing events for this calendar
        site_events = get_google_calendar_events(
            service, calendar_id, start_time
        )
        logger.normal(
            f"Found {len(site_events)} events in {site_code} Checkfront calendar"
        )
        
        # Filter Checkfront events for this site
        site_checkfront_events = [
            event for event in checkfront_events
            if event.summary.startswith(f"{site_code} -")
        ]
        logger.normal(
            f"Found {len(site_checkfront_events)} Checkfront events for {site_code}"
        )
        
        # Sync events to site-specific calendar
        sync_events_to_calendar(
            service,
            calendar_id,
            [],  # No HipCamp events for site-specific calendars
            site_checkfront_events,
            site_events
        )


def main():
    """
    Main command-line function to run the calendar sync process.
    """
    parser = argparse.ArgumentParser(
        description="Sync calendars between HipCamp, Checkfront, and Google Calendar."
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase verbosity"
    )
    args = parser.parse_args()

    # Set log level based on verbosity
    if args.verbose >= 2:
        logger.level = LogLevel.DEBUG
    elif args.verbose == 1:
        logger.level = LogLevel.NORMAL

    run_sync()


if __name__ == "__main__":
    main()
