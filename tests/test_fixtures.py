"""Unit tests verifying test fixture projects (vulnerable-demo-app and clean-app)."""

import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture_app(fixture_name: str):
    """Load the FastAPI app from a fixture directory using isolated module loading."""
    app_dir = FIXTURES_DIR / fixture_name
    config_path = app_dir / "config.py"
    main_path = app_dir / "main.py"

    # Load fixture's config module
    config_spec = importlib.util.spec_from_file_location(f"{fixture_name}_config", config_path)
    config_mod = importlib.util.module_from_spec(config_spec)
    config_spec.loader.exec_module(config_mod)

    # Load fixture's main module with the config injected
    import sys
    sys.modules["config"] = config_mod
    main_spec = importlib.util.spec_from_file_location(f"{fixture_name}_main", main_path)
    main_mod = importlib.util.module_from_spec(main_spec)
    main_spec.loader.exec_module(main_mod)
    sys.modules.pop("config", None)

    return main_mod.app


def test_vulnerable_demo_app_files_exist() -> None:
    """Verify all required files exist in vulnerable-demo-app fixture."""
    app_dir = FIXTURES_DIR / "vulnerable-demo-app"
    assert app_dir.is_dir()
    assert (app_dir / "README.md").is_file()
    assert (app_dir / "requirements.txt").is_file()
    assert (app_dir / "config.py").is_file()
    assert (app_dir / "main.py").is_file()
    assert (app_dir / ".gitignore").is_file()


def test_vulnerable_demo_app_has_planted_issues() -> None:
    """Verify vulnerable-demo-app fixture contains exactly the 3 documented planted issues."""
    app_dir = FIXTURES_DIR / "vulnerable-demo-app"
    
    # 1. Check for hardcoded API key on line 12
    config_content = (app_dir / "config.py").read_text(encoding="utf-8")
    lines = config_content.splitlines()
    assert len(lines) >= 12
    assert "API_KEY" in lines[11]  # 0-indexed line 11 is line 12
    assert "sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI" in lines[11]
    assert "DEBUG = False" in config_content

    # 2. Check that .gitignore does NOT ignore .env
    gitignore_content = (app_dir / ".gitignore").read_text(encoding="utf-8")
    assert ".env" not in gitignore_content

    # 3. Check for hardcoded port with standard 0.0.0.0 host
    main_content = (app_dir / "main.py").read_text(encoding="utf-8")
    assert 'host="0.0.0.0"' in main_content
    assert "port=8000" in main_content


def test_extra_issues_app_has_planted_issues() -> None:
    """Verify extra-issues-app fixture contains debug mode, localhost bind, and junk files."""
    app_dir = FIXTURES_DIR / "extra-issues-app"
    assert app_dir.is_dir()

    config_content = (app_dir / "config.py").read_text(encoding="utf-8")
    assert "DEBUG = True" in config_content

    main_content = (app_dir / "main.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in main_content

    assert (app_dir / "node_modules").is_dir()
    assert (app_dir / ".DS_Store").is_file()


def test_clean_app_files_exist() -> None:
    """Verify all required files exist in clean-app fixture."""
    app_dir = FIXTURES_DIR / "clean-app"
    assert app_dir.is_dir()
    assert (app_dir / "README.md").is_file()
    assert (app_dir / "requirements.txt").is_file()
    assert (app_dir / "config.py").is_file()
    assert (app_dir / "main.py").is_file()
    assert (app_dir / ".gitignore").is_file()


def test_clean_app_is_properly_configured() -> None:
    """Verify clean-app fixture adheres to safe deployment standards."""
    app_dir = FIXTURES_DIR / "clean-app"
    
    # 1. No hardcoded secrets
    config_content = (app_dir / "config.py").read_text(encoding="utf-8")
    assert "sk-proj-" not in config_content
    assert "os.getenv" in config_content

    # 2. .gitignore properly ignores .env
    gitignore_content = (app_dir / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore_content

    # 3. Uses dynamic port
    main_content = (app_dir / "main.py").read_text(encoding="utf-8")
    assert "port=PORT" in main_content or "PORT" in main_content


def test_vulnerable_app_endpoints() -> None:
    """Run vulnerable app and verify / and /health return 200 OK."""
    app = load_fixture_app("vulnerable-demo-app")
    client = TestClient(app)

    r_root = client.get("/")
    assert r_root.status_code == 200
    assert r_root.json() == {"message": "Welcome to Student Notes API", "status": "running"}

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json() == {"status": "ok"}


def test_clean_app_endpoints() -> None:
    """Run clean app and verify / and /health return 200 OK."""
    app = load_fixture_app("clean-app")
    client = TestClient(app)

    r_root = client.get("/")
    assert r_root.status_code == 200
    assert r_root.json() == {"message": "Welcome to Clean Notes API", "status": "running"}

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json() == {"status": "ok"}
