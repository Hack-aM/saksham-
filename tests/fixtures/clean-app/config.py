"""Configuration for clean FastAPI application."""

import os

APP_NAME = os.getenv("APP_NAME", "CleanNotesAPI")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

# Secrets are read safely from environment
API_KEY = os.getenv("API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./notes.db")
