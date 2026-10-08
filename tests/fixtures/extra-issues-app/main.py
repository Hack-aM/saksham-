"""Main entry point for extra issues test fixture app."""

import uvicorn
from fastapi import FastAPI
from config import APP_NAME, APP_VERSION, DEBUG, PORT

# Planted Issue 1: Debug mode enabled
app = FastAPI(title=APP_NAME, version=APP_VERSION, debug=DEBUG)


@app.get("/")
def read_root():
    return {"status": "ok", "app": "ExtraIssuesAPI"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    # Planted Issue 2: Hardcoded localhost bind address
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=True)
