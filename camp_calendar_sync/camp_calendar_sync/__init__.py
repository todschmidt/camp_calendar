"""
Camp Calendar Sync Package

This package provides functionality to synchronize HipCamp and Checkfront
reservations with Google Calendar.
"""

from .core import (
    CalendarEvent,
    LogLevel,
    Logger,
    CheckfrontAPI,
    get_google_credentials,
    fetch_hipcamp_events,
    fetch_checkfront_events,
    get_google_calendar_events,
    sync_events_to_calendar,
)

__version__ = "0.1.0" 