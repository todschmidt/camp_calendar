"""
Calendar Sync Script

This script synchronizes Lodgify reservations with a Google Calendar.
It fetches reservations from Lodgify's API and creates/updates/deletes
corresponding events in a specified Google Calendar.

Features:
- Fetches all Lodgify reservations with pagination support
- Filters reservations by status, property, and trash status
- Syncs events to Google Calendar with metadata
- Handles event updates and deletions
- Maintains sync state using extended properties

Requirements:
- Google Calendar API credentials (credentials.json)
- Lodgify API key (set as LODGIFY_API_KEY environment variable)
- Python packages: google-auth-oauthlib, google-auth-httplib2, 
  google-api-python-client, requests

Usage:
1. Set up Google Calendar API credentials
2. Set LODGIFY_API_KEY environment variable
3. Run the script: python main.py
"""

import datetime
import os.path
import requests
from typing import List, Optional, Dict

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


def get_property_display_name(property_name: str) -> str:
    """
    Convert Lodgify property names to display names.
    
    Args:
        property_name: The property name from Lodgify
        
    Returns:
        Formatted display name for the property
    """
    # Map of property names to display names
    property_map = {
        "Log Cabin Suite1-RideIn RideOut": "UC",
        "Log Cabin Suite2-RideIn RideOut": "LC"
    }
    return property_map.get(property_name, property_name)


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
                print(f"Error refreshing token: {e}")
                print("Forcing new authentication...")
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
    Represents a calendar event from any source (Google Calendar or Lodgify).
    
    Attributes:
        start_time: Start time of the event
        end_time: End time of the event
        summary: Event title/summary
        description: Optional event description
        source: Source of the event (e.g., "lodgify" or "google_calendar")
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


def fetch_lodgify_events(
    api_key: str,
    start_date: datetime.datetime,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    include_trash: bool = False,
) -> List[CalendarEvent]:
    """
    Fetch events from Lodgify API and convert them to CalendarEvent objects.
    
    Args:
        api_key: The Lodgify API key
        start_date: The start date to fetch events from
        property_id: Optional property ID to filter events
        status: Optional status to filter events (e.g., "Booked")
        include_trash: Whether to include events in trash
        
    Returns:
        List of CalendarEvent objects
        
    Raises:
        requests.exceptions.RequestException: If the API request fails
    """
    headers = {
        "X-APIKey": api_key,
        "Content-Type": "application/json"
    }
    
    # Convert start_date to ISO format for API
    start_date_iso = start_date.isoformat()
    
    url = "https://api.lodgify.com/v1/reservation"
    
    # Initialize parameters
    params = {
        "periodStart": start_date_iso,
        "limit": 50,  # Maximum allowed per page
        "offset": 0,
        "trash": str(include_trash).lower()
    }
    
    if property_id:
        params["propertyId"] = property_id
    if status:
        params["status"] = status
    
    all_events = []
    
    try:
        while True:
            response = requests.get(
                url,
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            items = data.get("items", [])
            
            if not items:
                break
                
            for reservation in items:
                # Convert dates to datetime objects and set to noon EDT
                # This ensures the date is correct in the local timezone
                start_time = datetime.datetime.fromisoformat(
                    f"{reservation['arrival']}T12:00:00"
                ).replace(tzinfo=datetime.timezone.utc)
                end_time = datetime.datetime.fromisoformat(
                    f"{reservation['departure']}T12:00:00"
                ).replace(tzinfo=datetime.timezone.utc)
                
                # Create description with guest info
                guest_name = reservation["guest"]["guest_name"]["full_name"]
                property_name = reservation["property_name"]
                display_name = get_property_display_name(property_name)
                status = reservation["status"]
                
                description = (
                    f"Guest: {guest_name}\n"
                    f"Property: {display_name}\n"
                    f"Status: {status}\n"
                    f"People: {reservation['people']}\n"
                    f"Source: Lodgify\n"
                    f"Lodgify ID: {reservation['id']}"
                )
                
                event = CalendarEvent(
                    start_time=start_time,
                    end_time=end_time,
                    summary=f"{display_name} - {guest_name}",
                    description=description,
                    source="lodgify",
                    source_id=str(reservation["id"])
                )
                all_events.append(event)
            
            # If we got less than the limit, we've reached the end
            if len(items) < params["limit"]:
                break
                
            # Update offset for next page
            params["offset"] += params["limit"]
            
        return all_events
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Lodgify events: {e}")
        return []


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
            # Get the Lodgify ID from extended properties if it exists
            lodgify_id = None
            if "extendedProperties" in event:
                private_props = event["extendedProperties"].get("private", {})
                lodgify_id = private_props.get("lodgify_id")
            
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
                source="google_calendar",
                source_id=event["id"],
                google_event_id=event["id"]
            )
            if lodgify_id:
                calendar_event.source = "lodgify"
                calendar_event.source_id = lodgify_id
            events.append(calendar_event)
            
        return events
        
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []


def sync_events_to_calendar(
    service,
    calendar_id: str,
    lodgify_events: List[CalendarEvent],
    existing_events: List[CalendarEvent]
) -> None:
    """
    Sync Lodgify events to Google Calendar.
    
    This function:
    1. Creates new events for new Lodgify reservations
    2. Updates existing events if they've changed
    3. Deletes events that no longer exist in Lodgify
    
    Args:
        service: Google Calendar API service instance
        calendar_id: ID of the calendar to sync events to
        lodgify_events: List of current Lodgify events
        existing_events: List of existing Google Calendar events
        
    Raises:
        HttpError: If any Google Calendar API operation fails
    """
    # Create a map of existing events by Lodgify ID
    existing_lodgify_events: Dict[str, CalendarEvent] = {}
    google_event_ids: Dict[str, str] = {}  # Maps Lodgify ID to Google Calendar ID
    
    for event in existing_events:
        if event.source == "lodgify" and event.source_id:
            existing_lodgify_events[event.source_id] = event
            # Store the Google Calendar event ID
            if event.google_event_id:
                google_event_ids[event.source_id] = event.google_event_id
    
    # Create a map of new events by Lodgify ID
    new_lodgify_events = {
        event.source_id: event
        for event in lodgify_events
        if event.source_id
    }
    
    # Delete events that no longer exist in Lodgify
    for lodgify_id, event in existing_lodgify_events.items():
        if lodgify_id not in new_lodgify_events:
            try:
                # Use the Google Calendar event ID for deletion
                google_event_id = google_event_ids.get(lodgify_id)
                if google_event_id:
                    service.events().delete(
                        calendarId=calendar_id,
                        eventId=google_event_id
                    ).execute()
                    print(f"Deleted event: {event.summary}")
            except HttpError as error:
                if "insufficientPermissions" in str(error):
                    print(
                        "Error: Insufficient permissions to delete events. "
                        "Please check your Google Calendar API scopes and "
                        "ensure you have write access to the calendar."
                    )
                else:
                    print(f"Error deleting event: {error}")
    
    # Create or update events
    for lodgify_id, event in new_lodgify_events.items():
        # Format dates for all-day events (YYYY-MM-DD)
        start_date = event.start_time.strftime("%Y-%m-%d")
        end_date = event.end_time.strftime("%Y-%m-%d")
        
        google_event = {
            "summary": event.summary,
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
                    "lodgify_id": lodgify_id,
                    "synced_by_script": "true"
                }
            }
        }
        
        try:
            if lodgify_id in existing_lodgify_events:
                # Update existing event using Google Calendar event ID
                google_event_id = google_event_ids.get(lodgify_id)
                if google_event_id:
                    service.events().update(
                        calendarId=calendar_id,
                        eventId=google_event_id,
                        body=google_event
                    ).execute()
                    print(f"Updated event: {event.summary}")
            else:
                # Create new event
                created_event = service.events().insert(
                    calendarId=calendar_id,
                    body=google_event
                ).execute()
                print(f"Created event: {event.summary}")
                # Store the Google Calendar ID for future updates
                google_event_ids[lodgify_id] = created_event["id"]
        except HttpError as error:
            if "insufficientPermissions" in str(error):
                print(
                    "Error: Insufficient permissions to modify events. "
                    "Please check your Google Calendar API scopes and "
                    "ensure you have write access to the calendar."
                )
            else:
                print(f"Error syncing event: {error}")


def main():
    """
    Main function that orchestrates the calendar sync process.
    
    This function:
    1. Authenticates with Google Calendar API
    2. Finds the target calendar
    3. Fetches events from both Google Calendar and Lodgify
    4. Syncs the events
    
    The script requires:
    - Google Calendar API credentials (credentials.json)
    - Lodgify API key (LODGIFY_API_KEY environment variable)
    """
    # Get credentials without forcing refresh
    creds = get_google_credentials(force_refresh=False)

    try:
        service = build("calendar", "v3", credentials=creds)

        # First, list all calendars to find the DBR Cabin Rentals calendar
        print("Listing all calendars...")
        calendar_list = service.calendarList().list().execute()
        dbr_calendar_id = None
        
        for calendar in calendar_list.get('items', []):
            print(f"Calendar: {calendar['summary']} (ID: {calendar['id']})")
            if calendar['summary'] == "DBR Cabin Rentals":
                dbr_calendar_id = calendar['id']
                break
        
        if not dbr_calendar_id:
            print("DBR Cabin Rentals calendar not found!")
            return

        # Get events from both sources
        start_time = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Get Google Calendar events
        google_events = get_google_calendar_events(
            service, dbr_calendar_id, start_time
        )
        print(f"\nFound {len(google_events)} events in Google Calendar")
        
        # Get Lodgify events (you'll need to set your API key)
        lodgify_api_key = os.getenv("LODGIFY_API_KEY")
        if lodgify_api_key:
            # You can customize these parameters as needed
            lodgify_events = fetch_lodgify_events(
                api_key=lodgify_api_key,
                start_date=start_time,
                status="Booked",  # Only get confirmed bookings
                include_trash=False  # Don't include deleted bookings
            )
            print(f"Found {len(lodgify_events)} events in Lodgify")
            
            # Sync events to Google Calendar
            sync_events_to_calendar(
                service, dbr_calendar_id, lodgify_events, google_events
            )
        else:
            print("LODGIFY_API_KEY environment variable not set")
            lodgify_events = []

    except HttpError as error:
        if "insufficientPermissions" in str(error):
            print(
                "Error: Insufficient permissions to access Google Calendar. "
                "Please check your Google Calendar API scopes and "
                "ensure you have the necessary permissions."
            )
        else:
            print(f"An error occurred: {error}")


if __name__ == "__main__":
    main()