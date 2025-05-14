from setuptools import setup, find_packages

setup(
    name="camp_calendar_sync",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "google-auth-oauthlib",
        "google-auth-httplib2",
        "google-api-python-client",
        "requests",
        "icalendar",
    ],
    entry_points={
        "console_scripts": [
            "camp-sync=camp_calendar_sync.cli:main",
        ],
    },
) 