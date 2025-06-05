# Camp Calendar Sync

A Python package for synchronizing HipCamp and Checkfront reservations with Google Calendar.

## Features

- Fetches events from multiple HipCamp iCal feeds
- Fetches events from Checkfront iCal feed
- Maps HipCamp sites to display names
- Syncs events to Google Calendar with metadata
- Handles event updates and deletions
- Maintains sync state using extended properties
- Supports both CLI and AWS Lambda usage

## Installation

```bash
pip install -e .
```

## Usage

### Command Line Interface

The package provides a command-line interface for manual synchronization:

```bash
camp-sync [options]
```

Options:
- `-v, --verbose`: Increase verbosity (use -v for warnings, -vv for debug)
- `--credentials PATH`: Path to Google Calendar API credentials file (default: credentials.json)
- `--token PATH`: Path to store/load Google Calendar API token (default: token.json)
- `--hipcamp-urls PATH`: Path to JSON file containing HipCamp iCal URLs (default: hipcamp_urls.json)
- `--checkfront-url PATH`: Path to file containing Checkfront iCal URL (default: checkfront_url.txt)
- `--calendar-name NAME`: Name of the Google Calendar to sync to (default: DBR Camping)

### AWS Lambda

The package can also be used as an AWS Lambda function. The Lambda handler expects the following environment variables:

- `HIPCAMP_URLS`: JSON string mapping site names to iCal URLs
- `CHECKFRONT_URL`: Checkfront iCal URL
- `CALENDAR_NAME`: Name of the Google Calendar to sync to (default: DBR Camping)
- `GOOGLE_CREDENTIALS`: Google Calendar API credentials JSON
- `GOOGLE_TOKEN`: Optional Google Calendar API token JSON
- `LOG_LEVEL`: Logging level (NORMAL, WARN, or DEBUG)

Example Lambda event:
```json
{
  "source": "aws.events",
  "detail-type": "Scheduled Event"
}
```

## Configuration Files

### HipCamp URLs (hipcamp_urls.json)

```json
{
  "HillTop #1": "https://www.hipcamp.com/...",
  "HillTop #2": "https://www.hipcamp.com/...",
  "#1 Dropping In": "https://www.hipcamp.com/..."
}
```

### Checkfront URL (checkfront_url.txt)

```
https://dupont-bike-retreat.checkfront.com/view/bookings/ics/?id=...
```

### Google Calendar API Credentials (credentials.json)

Download from the Google Cloud Console:
1. Go to the Google Cloud Console
2. Select your project
3. Go to APIs & Services > Credentials
4. Create an OAuth 2.0 Client ID
5. Download the JSON file

## Development

### Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

### Running Tests

```bash
pytest
```

### Building

```bash
python -m build
```

## License

This project is licensed under the MIT License - see the LICENSE file for details. 