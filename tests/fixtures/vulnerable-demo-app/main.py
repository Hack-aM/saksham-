"""Main entry point for vulnerable demo student app."""

import uvicorn
from fastapi import FastAPI
from config import APP_NAME, APP_VERSION, DEBUG

app = FastAPI(title=APP_NAME, version=APP_VERSION, debug=DEBUG)


@app.get("/")
def read_root():
    return {"message": "Welcome to Student Notes API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    # Planted Issue: Hardcoded port
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

