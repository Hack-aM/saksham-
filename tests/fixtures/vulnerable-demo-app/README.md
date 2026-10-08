# Vulnerable Demo App (Test Fixture)

This is a sample student FastAPI project created for testing Saksham's audit, detection, and auto-fixing pipeline.

## Planted Issues for Audit:
1. **Hardcoded Secret Key (High Severity)**: In `config.py` line 12, an `API_KEY` is hardcoded as a plain string.
2. **Missing `.env` in `.gitignore` (Medium Severity)**: The `.gitignore` file ignores `__pycache__` and `venv` but does not ignore `.env`.
3. **Hardcoded Port (Medium Severity)**: In `main.py`, `uvicorn.run("main:app", port=8000)` hardcodes port 8000 rather than reading from `PORT` environment variable.

