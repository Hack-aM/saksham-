"""Main entry point for clean FastAPI application."""

import uvicorn
from fastapi import FastAPI
from config import APP_NAME, APP_VERSION, DEBUG, PORT, HOST

app = FastAPI(title=APP_NAME, version=APP_VERSION, debug=DEBUG)


@app.get("/")
def read_root():
    return {"message": "Welcome to Clean Notes API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
