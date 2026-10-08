"""Configuration for extra issues test fixture app."""

import os

APP_NAME = os.getenv("APP_NAME", "ExtraIssuesAPI")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

# Planted Issue 1: Debug mode enabled in configuration
DEBUG = True

PORT = int(os.getenv("PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./notes.db")
