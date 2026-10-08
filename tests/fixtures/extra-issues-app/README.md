# Extra Issues App (Test Fixture)

This fixture is used to test configuration checks for debug mode, hardcoded localhost binding, and junk files.

## Planted Issues:
1. **Debug & Reload Mode Enabled (Low Severity)**: `DEBUG = True` in `config.py` and `reload=True` in `main.py`.
2. **Hardcoded Localhost Bind (Medium Severity)**: `host="127.0.0.1"` in `main.py`.
3. **Junk Files (Low Severity)**: `node_modules/` directory and `.DS_Store` file.
