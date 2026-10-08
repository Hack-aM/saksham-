"""Unit and integration tests for POST /analyze endpoint (T14)."""

import io
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db import get_analysis, init_db
from main import (
    RUNS,
    ActiveRun,
    app,
    cleanup_all_workspaces_on_startup,
    cleanup_expired_workspaces,
)
from schemas import SeverityEnum

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VULNERABLE_APP_DIR = FIXTURES_DIR / "vulnerable-demo-app"
CLEAN_APP_DIR = FIXTURES_DIR / "clean-app"
EXTRA_ISSUES_APP_DIR = FIXTURES_DIR / "extra-issues-app"


def _create_zip_from_directory(dir_path: Path) -> io.BytesIO:
    """Helper to create an in-memory zip archive from a directory, ignoring __pycache__."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in dir_path.rglob("*"):
            if file_path.is_file() and "__pycache__" not in file_path.parts and ".pytest_cache" not in file_path.parts:
                arcname = file_path.relative_to(dir_path).as_posix()
                zf.write(file_path, arcname=arcname)
    buf.seek(0)
    return buf


@pytest.fixture
def client(tmp_path):
    """Test client with isolated test database."""
    test_db = str(tmp_path / "test_saksham.db")
    init_db(test_db)
    settings = get_settings()
    original_db = settings.db_path
    settings.db_path = test_db
    with TestClient(app) as test_client:
        yield test_client
    settings.db_path = original_db


def test_analyze_vulnerable_demo_app(client):
    """Verify that POST /analyze on vulnerable demo app returns score 40 and 3 planted issues."""
    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    response = client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["project_name"] == "vulnerable-demo-app"
    assert data["stack"] == "Python / FastAPI"
    assert data["score"] == 40
    assert len(data["issues"]) == 3
    assert len(data["patches"]) >= 3
    assert len(data["reasons"]) == 3
    assert data["run_id"] is not None
    assert data["id"] is not None

    # Verify run is stored in memory
    run_id = data["run_id"]
    assert run_id in RUNS
    active_run = RUNS[run_id]
    assert active_run.score == 40
    assert active_run.workspace_dir.exists()

    # Verify persisted in database
    db_record = get_analysis(data["id"], db_path=get_settings().db_path)
    assert db_record is not None
    assert db_record["score"] == 40
    assert len(db_record["issues"]) == 3


def test_analyze_clean_app(client):
    """Verify that POST /analyze on clean app returns score 100 with zero issues."""
    zip_buf = _create_zip_from_directory(CLEAN_APP_DIR)
    response = client.post(
        "/analyze",
        files={"file": ("clean-app.zip", zip_buf, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["project_name"] == "clean-app"
    assert data["stack"] == "Python / FastAPI"
    assert data["score"] == 100
    assert len(data["issues"]) == 0
    assert len(data["reasons"]) == 0


def test_analyze_extra_issues_app(client):
    """Verify that POST /analyze on extra-issues-app detects debug, localhost, and junk files."""
    zip_buf = _create_zip_from_directory(EXTRA_ISSUES_APP_DIR)
    response = client.post(
        "/analyze",
        files={"file": ("extra-issues-app.zip", zip_buf, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()

    titles = [issue["title"] for issue in data["issues"]]
    assert any("Debug" in t for t in titles)
    assert any("localhost" in t.lower() or "127.0.0.1" in t for t in titles)
    assert any("junk" in t.lower() or "build artifact" in t.lower() for t in titles)


def test_analyze_non_zip_rejected(client):
    """Verify that uploading a non-zip file returns 400 Bad Request."""
    response = client.post(
        "/analyze",
        files={"file": ("malicious.txt", b"plain text content", "text/plain")},
    )
    assert response.status_code == 400
    assert "File must have a .zip extension" in response.json()["error"]


def test_analyze_path_traversal_zip_rejected(client):
    """Verify that a ZIP with path traversal is safely rejected with HTTP 400."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.py", "malicious_code = True")
    buf.seek(0)

    response = client.post(
        "/analyze",
        files={"file": ("traversal.zip", buf, "application/zip")},
    )
    assert response.status_code == 400
    assert "Path traversal detected" in response.json()["error"]


def test_startup_workspace_cleanup(tmp_path):
    """Verify that cleanup_all_workspaces_on_startup removes stale directories."""
    runs_dir = tmp_path / "tmp_runs"
    runs_dir.mkdir(parents=True)
    stale_dir = runs_dir / "stale_run_123"
    stale_dir.mkdir()
    (stale_dir / "dummy.txt").write_text("old file", encoding="utf-8")

    assert stale_dir.exists()
    cleanup_all_workspaces_on_startup(base_dir=runs_dir)
    assert not stale_dir.exists()


def test_ttl_workspace_cleanup(tmp_path):
    """Verify that cleanup_expired_workspaces purges expired runs."""
    fake_workspace = tmp_path / "fake_workspace"
    fake_workspace.mkdir()
    (fake_workspace / "main.py").write_text("# app", encoding="utf-8")

    simulated_run_id = "expired_test_run"
    RUNS[simulated_run_id] = ActiveRun(
        run_id=simulated_run_id,
        project_name="expired_proj",
        workspace_dir=fake_workspace,
        created_at=time.time() - 3600,  # 1 hour old
        scan_result=None,
        issues=[],
        score=100,
        reasons=[],
        history_status="history not available",
        patches=[],
    )

    cleanup_expired_workspaces(ttl_seconds=1800)
    assert simulated_run_id not in RUNS
    assert not fake_workspace.exists()


def test_analyze_persists_in_sqlite_without_raw_secrets(client):
    """Verify that sensitive tokens are redacted before saving analysis to SQLite."""
    # Read planted key from fixture config.py
    config_content = (VULNERABLE_APP_DIR / "config.py").read_text(encoding="utf-8")
    key_match = [line for line in config_content.splitlines() if "API_KEY =" in line]
    assert len(key_match) == 1
    raw_key = key_match[0].split('"')[1]

    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    response = client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    assert response.status_code == 200
    db_path = Path(get_settings().db_path)
    assert db_path.exists()

    # Read raw database binary content
    raw_db_content = db_path.read_bytes().decode("latin1", errors="ignore")
    # Assert that the raw secret key appears nowhere in the SQLite database file
    assert raw_key not in raw_db_content


