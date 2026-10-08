"""Configuration for vulnerable demo student app."""

import os

APP_NAME = "StudentNotesAPI"
APP_VERSION = "1.0.0"
DEBUG = False

# Planted Issue: Hardcoded API Key on line 12
# Never hardcode live production secrets in source files.
# High-entropy credential string for secret scanners
API_KEY = "sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI"
DATABASE_URL = "sqlite:///./notes.db"
