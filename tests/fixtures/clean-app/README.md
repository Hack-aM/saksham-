# Clean App (Test Fixture)

This is a clean, well-configured student FastAPI application adhering to deployment best practices.

## Configuration features:
1. **No Hardcoded Secrets**: Reads secrets safely via `os.getenv()`.
2. **Proper .gitignore**: `.env`, `__pycache__`, `venv`, and database files are properly ignored.
3. **Environment-driven Port**: Uses `PORT` environment variable for host binding.
4. **Health Check**: Implements `/health` endpoint returning 200 OK.
