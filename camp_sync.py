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
- Python packages: google-auth-oauthlib, google-auth-httplib2, 
  google-api-python-client, requests, icalendar

Usage:
1. Set up Google Calendar API credentials
2. Add HipCamp iCal URLs to the HIPCAMP_ICAL_URLS dictionary
3. Run the script: python camp_sync.py
"""

import datetime
import os.path
import re
import requests
from typing import List, Optional, Dict
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
                # Remove phone number if present (format: "Name - +1XXXXXXXXXX")
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
            # Get the HipCamp booking ID from extended properties if it exists
            booking_id = None
            if "extendedProperties" in event:
                private_props = event["extendedProperties"].get("private", {})
                booking_id = private_props.get("hipcamp_booking_id")
            
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
            if booking_id:
                calendar_event.source = "hipcamp"
                calendar_event.source_id = booking_id
            events.append(calendar_event)
            
        return events
        
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []


def sync_events_to_calendar(
    service,
    calendar_id: str,
    hipcamp_events: List[CalendarEvent],
    existing_events: List[CalendarEvent]
) -> None:
    """
    Sync HipCamp events to Google Calendar.
    
    This function:
    1. Creates new events for new HipCamp reservations
    2. Updates existing events if they've changed
    3. Deletes events that no longer exist in HipCamp
    
    Args:
        service: Google Calendar API service instance
        calendar_id: ID of the calendar to sync events to
        hipcamp_events: List of current HipCamp events
        existing_events: List of existing Google Calendar events
        
    Raises:
        HttpError: If any Google Calendar API operation fails
    """
    # Create a map of existing events by HipCamp booking ID
    existing_hipcamp_events: Dict[str, CalendarEvent] = {}
    google_event_ids: Dict[str, str] = {}  # Maps booking ID to Google Calendar ID
    
    for event in existing_events:
        if event.source == "hipcamp" and event.source_id:
            existing_hipcamp_events[event.source_id] = event
            # Store the Google Calendar event ID
            if event.google_event_id:
                google_event_ids[event.source_id] = event.google_event_id
    
    # Create a map of new events by booking ID
    new_hipcamp_events = {
        event.source_id: event
        for event in hipcamp_events
        if event.source_id
    }
    
    # Delete events that no longer exist in HipCamp
    for booking_id, event in existing_hipcamp_events.items():
        if booking_id not in new_hipcamp_events:
            try:
                # Use the Google Calendar event ID for deletion
                google_event_id = google_event_ids.get(booking_id)
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
    for booking_id, event in new_hipcamp_events.items():
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
                    "hipcamp_booking_id": booking_id,
                    "synced_by_script": "true"
                }
            }
        }
        
        try:
            if booking_id in existing_hipcamp_events:
                # Update existing event using Google Calendar event ID
                google_event_id = google_event_ids.get(booking_id)
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
                google_event_ids[booking_id] = created_event["id"]
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
    3. Fetches events from both Google Calendar and HipCamp
    4. Syncs the events
    
    The script requires:
    - Google Calendar API credentials (credentials.json)
    - HipCamp iCal URLs in the HIPCAMP_ICAL_URLS dictionary
    """
    # Get credentials without forcing refresh
    creds = get_google_credentials(force_refresh=False)

    try:
        service = build("calendar", "v3", credentials=creds)

        # First, list all calendars to find the DBR Camping calendar
        print("Listing all calendars...")
        calendar_list = service.calendarList().list().execute()
        dbr_calendar_id = None
        
        for calendar in calendar_list.get('items', []):
            print(f"Calendar: {calendar['summary']} (ID: {calendar['id']})")
            if calendar['summary'] == "DBR Camping":
                dbr_calendar_id = calendar['id']
                break
        
        if not dbr_calendar_id:
            print("DBR Camping calendar not found!")
            return

        # Get events from both sources
        start_time = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Get Google Calendar events
        google_events = get_google_calendar_events(
            service, dbr_calendar_id, start_time
        )
        print(f"\nFound {len(google_events)} events in Google Calendar")
        
        # Get HipCamp events
        hipcamp_events = fetch_hipcamp_events()
        print(f"Found {len(hipcamp_events)} events in HipCamp")
        
        # Sync events to Google Calendar
        sync_events_to_calendar(
            service, dbr_calendar_id, hipcamp_events, google_events
        )

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
