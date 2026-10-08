"""Unit and integration tests for POST /approve endpoint (T19)."""

import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db import init_db
from main import RUNS, app
from schemas import SeverityEnum
from tests.test_analyze import _create_zip_from_directory

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VULNERABLE_APP_DIR = FIXTURES_DIR / "vulnerable-demo-app"
CLEAN_APP_DIR = FIXTURES_DIR / "clean-app"


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


def test_approve_applies_approved_patches_and_passes_secret_gate(client):
    """Verify that approving all patches on vulnerable fixture fixes issues, raises score, and passes."""
    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    analyze_res = client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    assert analyze_res.status_code == 200
    analyze_data = analyze_res.json()
    run_id = analyze_data["run_id"]
    patches = analyze_data["patches"]
    assert len(patches) >= 3

    # Approve all 3 issue patches
    approved_patch_ids = [p["id"] for p in patches if p["file"] in ["config.py", ".gitignore", "main.py"]]

    approve_res = client.post(
        "/approve",
        json={
            "run_id": run_id,
            "approved_patch_ids": approved_patch_ids,
            "repo_name": "repaired-demo-app",
        },
    )
    assert approve_res.status_code == 200
    approve_data = approve_res.json()

    assert approve_data["status"] == "applied"
    assert approve_data["run_id"] == run_id
    assert approve_data["applied_patches_count"] == len(approved_patch_ids)
    assert approve_data["score"] == 100
    assert len(approve_data["remaining_issues"]) == 0
    assert "Secret gate passed" in approve_data["message"]

    # Verify that files in workspace on disk were actually patched
    workspace_dir = RUNS[run_id].workspace_dir
    config_content = (workspace_dir / "config.py").read_text(encoding="utf-8")
    assert 'API_KEY = os.getenv("API_KEY", "")' in config_content

    gitignore_content = (workspace_dir / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore_content


def test_approve_blocks_when_secret_patch_is_not_approved(client):
    """Verify that the secret gate blocks push when High severity secret leak is left unresolved."""
    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    analyze_res = client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    assert analyze_res.status_code == 200
    analyze_data = analyze_res.json()
    run_id = analyze_data["run_id"]
    patches = analyze_data["patches"]

    # Approve ONLY the port patch in main.py, leaving API_KEY secret unpatched!
    port_patch_ids = [p["id"] for p in patches if p["file"] == "main.py"]
    assert len(port_patch_ids) == 1

    approve_res = client.post(
        "/approve",
        json={
            "run_id": run_id,
            "approved_patch_ids": port_patch_ids,
        },
    )
    assert approve_res.status_code == 200
    approve_data = approve_res.json()

    # Secret gate MUST block
    assert approve_data["status"] == "blocked"
    assert "Push blocked: unresolved High-severity secret leaks" in approve_data["message"]
    # Remaining issues should contain the High severity secret issue
    assert any(i["severity"] == "High" for i in approve_data["remaining_issues"])


def test_approve_nonexistent_run_id_returns_404(client):
    """Verify that calling /approve with a non-existent run_id returns HTTP 404."""
    response = client.post(
        "/approve",
        json={
            "run_id": "nonexistent_fake_run_123",
            "approved_patch_ids": ["p-1"],
        },
    )
    assert response.status_code == 404
    assert "not found or workspace expired" in response.json()["detail"]


def test_approve_clean_app_with_empty_patches_passes(client):
    """Verify that approving a clean app with 0 patches succeeds immediately."""
    zip_buf = _create_zip_from_directory(CLEAN_APP_DIR)
    analyze_res = client.post(
        "/analyze",
        files={"file": ("clean-app.zip", zip_buf, "application/zip")},
    )
    assert analyze_res.status_code == 200
    run_id = analyze_res.json()["run_id"]

    approve_res = client.post(
        "/approve",
        json={
            "run_id": run_id,
            "approved_patch_ids": [],
        },
    )
    assert approve_res.status_code == 200
    approve_data = approve_res.json()

    assert approve_data["status"] == "applied"
    assert approve_data["applied_patches_count"] == 0
    assert approve_data["score"] == 100
