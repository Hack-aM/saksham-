"""End-to-End Happy Path and Integration Regression Tests for Saksham (T29).

Validates the full pipeline:
ZIP Upload -> Analyze -> Audit -> Approve Patches -> Patch Apply -> Secret Gate
-> Mocked GitHub Push -> Mocked Render Deploy -> Mocked Verification -> SSE Progress
-> Terminal Complete -> History & DB Persistence -> Security & Failure Regressions.

Strict Safety:
- Deterministic mocks for external boundaries (GitHub, Render, Gemini, HTTP health checks).
- Project code is NEVER executed locally on host.
- Zero secrets in DB, SSE, logs, or responses.
"""

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from config import get_settings
from db import get_analysis, init_db, list_analyses, list_deployments
from deployer import RenderDeployResult, SelfFixAttempt, SelfFixResult, VerificationResult
from main import RUNS, app
from schemas import SeverityEnum, StageEnum
from tests.test_analyze import _create_zip_from_directory

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VULNERABLE_APP_DIR = FIXTURES_DIR / "vulnerable-demo-app"
CLEAN_APP_DIR = FIXTURES_DIR / "clean-app"


@pytest.fixture
def isolated_client(tmp_path):
    """Create test client with isolated SQLite database and fresh settings."""
    test_db = str(tmp_path / "test_e2e_saksham.db")
    init_db(test_db)
    settings = get_settings()
    original_db = settings.db_path
    original_gh_token = settings.github_token
    original_render_key = settings.render_api_key

    settings.db_path = test_db
    settings.github_token = "ghp_mocktoken1234567890abcdefghijklmnopqrst"
    settings.render_api_key = "rnd_mockkey1234567890abcdefghijklmnop"

    with TestClient(app) as test_client:
        yield test_client

    settings.db_path = original_db
    settings.github_token = original_gh_token
    settings.render_api_key = original_render_key


# =========================================================================
# 1. HAPPY PATH END-TO-END TEST
# =========================================================================

def test_full_happy_path_e2e_flow(isolated_client):
    """Validate the complete Saksham happy-path flow from upload to live completion and history."""
    # 1. Upload ZIP
    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    analyze_res = isolated_client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    assert analyze_res.status_code == 200
    analysis = analyze_res.json()

    run_id = analysis["run_id"]
    assert run_id is not None
    assert analysis["project_name"] == "vulnerable-demo-app"
    assert analysis["stack"] == "Python / FastAPI"
    assert analysis["score"] < 100  # Initial score deducted due to secrets & config issues
    assert len(analysis["issues"]) >= 3
    assert len(analysis["patches"]) >= 3

    # Verify no raw secrets returned in issues or patches
    for issue in analysis["issues"]:
        assert "sk-proj-" not in issue["title"]
        assert "sk-proj-" not in issue["explanation"]

    # 2. Mock external integrations (GitHub, Render, Health Verification)
    mock_push_info = {
        "repo_url": "https://github.com/mock-user/vulnerable-demo-app",
        "clone_url": "https://github.com/mock-user/vulnerable-demo-app.git",
        "commit_sha": "a1b2c3d",
        "repo_name": "vulnerable-demo-app",
        "private": True,
    }

    mock_deploy_info = RenderDeployResult(
        service_id="srv-mock12345",
        service_name="vulnerable-demo-app",
        repo_url="https://github.com/mock-user/vulnerable-demo-app",
        live_url="https://vulnerable-demo-app.onrender.com",
        deploy_id="dep-mock67890",
        status="live",
        created_at=1700000000.0,
    )

    mock_verification = VerificationResult(
        url="https://vulnerable-demo-app.onrender.com/health",
        healthy=True,
        status="success",
        http_status=200,
        response_time_ms=85.2,
    )

    mock_selffix_res = SelfFixResult(
        success=True,
        attempts_count=1,
        final_verification=mock_verification,
        history=[
            SelfFixAttempt(
                attempt=1,
                verification_status="success",
                http_status=200,
            )
        ],
        live_url="https://vulnerable-demo-app.onrender.com",
        message="Service is healthy on attempt 1",
    )

    # 3. Approve Patches with Mocked Integrations
    with patch("main.push_workspace_to_github", return_value=mock_push_info) as mock_gh, \
         patch("main.deploy_project_to_render", return_value=mock_deploy_info) as mock_rnd, \
         patch("main.run_self_fix_loop", return_value=mock_selffix_res) as mock_vfy:

        approved_ids = [p["id"] for p in analysis["patches"]]
        approve_res = isolated_client.post(
            "/approve",
            json={
                "run_id": run_id,
                "approved_patch_ids": approved_ids,
                "repo_name": "vulnerable-demo-app",
                "visibility": "private",
            },
        )

        assert approve_res.status_code == 200
        approve_data = approve_res.json()
        assert approve_data["status"] == "applied"
        assert approve_data["score"] == 100
        assert len(approve_data["remaining_issues"]) == 0

        # Verify mocks were called with safe parameters
        mock_gh.assert_called_once()
        mock_rnd.assert_called_once()
        mock_vfy.assert_called_once()

    # 4. SSE Progress Events Verification
    events_res = isolated_client.get(f"/events/{run_id}")
    assert events_res.status_code == 200
    assert "text/event-stream" in events_res.headers["content-type"]

    event_lines = events_res.text.split("\n\n")
    events = []
    for block in event_lines:
        if block.startswith("data: "):
            events.append(json.loads(block[6:]))

    stages_present = [e["stage"] for e in events]
    assert StageEnum.UPLOAD.value in stages_present
    assert StageEnum.SCAN.value in stages_present
    assert StageEnum.AUDIT.value in stages_present
    assert StageEnum.APPROVE.value in stages_present
    assert StageEnum.GITHUB.value in stages_present
    assert StageEnum.DEPLOY.value in stages_present
    assert StageEnum.VERIFY.value in stages_present
    assert StageEnum.COMPLETE.value in stages_present

    # Terminal complete event check
    complete_event = [e for e in events if e["stage"] == StageEnum.COMPLETE.value][-1]
    assert complete_event["status"] == "completed"
    assert "vulnerable-demo-app.onrender.com" in complete_event["message"]
    assert complete_event["details"]["live_url"] == "https://vulnerable-demo-app.onrender.com"

    # 5. History and SQLite Persistence Verification
    history_res = isolated_client.get("/history")
    assert history_res.status_code == 200
    history_data = history_res.json()

    assert len(history_data["analyses"]) >= 1
    assert len(history_data["deployments"]) >= 1

    deployment_record = history_data["deployments"][0]
    assert deployment_record["analysis_id"] == run_id
    assert deployment_record["live_url"] == "https://vulnerable-demo-app.onrender.com"
    assert deployment_record["platform"] == "Render"
    assert "200 OK" in deployment_record["health_status"]

    # 6. Strict Zero-Secret Leakage Check
    raw_history_text = json.dumps(history_data)
    assert "sk-proj-" not in raw_history_text
    assert "ghp_mocktoken" not in raw_history_text
    assert "rnd_mockkey" not in raw_history_text


# =========================================================================
# 2. SECURITY REGRESSIONS
# =========================================================================

def test_security_secret_gate_blocks_unapproved_secrets(isolated_client):
    """Verify that leaving high severity secret unapproved blocks pipeline and prevents GitHub/Render calls."""
    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    analyze_res = isolated_client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    analysis = analyze_res.json()
    run_id = analysis["run_id"]
    patches = analysis["patches"]

    # Approve ONLY the port patch (leaving secret unpatched)
    port_patch_ids = [p["id"] for p in patches if p["file"] == "main.py"]

    with patch("main.push_workspace_to_github") as mock_gh, \
         patch("main.deploy_project_to_render") as mock_rnd:

        approve_res = isolated_client.post(
            "/approve",
            json={
                "run_id": run_id,
                "approved_patch_ids": port_patch_ids,
            },
        )
        assert approve_res.status_code == 200
        approve_data = approve_res.json()
        assert approve_data["status"] == "blocked"
        assert "Push blocked: unresolved High-severity secret leaks remain" in approve_data["message"]

        # Neither GitHub push nor Render deploy should have been invoked
        mock_gh.assert_not_called()
        mock_rnd.assert_not_called()


def test_security_zero_secret_in_db_and_events(isolated_client):
    """Verify secrets are redacted and never written to database or emitted via SSE."""
    zip_buf = _create_zip_from_directory(VULNERABLE_APP_DIR)
    analyze_res = isolated_client.post(
        "/analyze",
        files={"file": ("vulnerable-demo-app.zip", zip_buf, "application/zip")},
    )
    run_id = analyze_res.json()["run_id"]

    # Inspect events
    events_res = isolated_client.get(f"/events/{run_id}")
    assert "sk-proj-" not in events_res.text

    # Inspect DB analyses
    db_analyses = list_analyses(db_path=get_settings().db_path)
    assert len(db_analyses) > 0
    assert "sk-proj-" not in json.dumps(db_analyses)


# =========================================================================
# 3. FAILURE REGRESSIONS
# =========================================================================

def test_failure_malformed_zip_upload(isolated_client):
    """Verify that uploading corrupt ZIP bytes returns 400 Bad Request."""
    corrupt_bytes = io.BytesIO(b"PK\x03\x04corrupted-archive-data")
    res = isolated_client.post(
        "/analyze",
        files={"file": ("corrupt.zip", corrupt_bytes, "application/zip")},
    )
    assert res.status_code == 400
    detail = res.json().get("detail", res.json().get("error", "")).lower()
    assert "zip" in detail or "valid" in detail or "corrupt" in detail or "invalid" in detail


def test_failure_upload_size_limit(isolated_client):
    """Verify that uploads exceeding 25MB are rejected with 413 Payload Too Large."""
    oversized_data = b"0" * (26 * 1024 * 1024)
    res = isolated_client.post(
        "/analyze",
        files={"file": ("large.zip", io.BytesIO(oversized_data), "application/zip")},
    )
    assert res.status_code == 413
    detail = res.json().get("detail", res.json().get("error", "")).lower()
    assert "25 mb" in detail or "size" in detail or "too large" in detail


def test_failure_unknown_run_id(isolated_client):
    """Verify that non-existent run_id returns 404 for /approve and /events."""
    res_app = isolated_client.post(
        "/approve",
        json={"run_id": "nonexistent-uuid-1234", "approved_patch_ids": []},
    )
    assert res_app.status_code == 404

    res_evt = isolated_client.get("/events/nonexistent-uuid-1234")
    assert res_evt.status_code == 404


def test_failure_github_push_error_handled(isolated_client):
    """Verify that GitHub failure in background is caught, redacted, and emitted as error event."""
    zip_buf = _create_zip_from_directory(CLEAN_APP_DIR)
    analyze_res = isolated_client.post(
        "/analyze",
        files={"file": ("clean-app.zip", zip_buf, "application/zip")},
    )
    run_id = analyze_res.json()["run_id"]

    secret_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz01"
    with patch("main.push_workspace_to_github", side_effect=Exception(f"GitHub API 500 error token {secret_token}")):
        approve_res = isolated_client.post(
            "/approve",
            json={"run_id": run_id, "approved_patch_ids": []},
        )
        assert approve_res.status_code == 200

    events_res = isolated_client.get(f"/events/{run_id}")
    assert events_res.status_code == 200
    event_blocks = [json.loads(b[6:]) for b in events_res.text.split("\n\n") if b.startswith("data: ")]
    error_events = [e for e in event_blocks if e["stage"] == StageEnum.ERROR.value]
    assert len(error_events) >= 1
    assert secret_token not in error_events[0]["message"]
    assert "[REDACTED]" in error_events[0]["message"] or "token" in error_events[0]["message"]


def test_failure_verification_failure_recorded(isolated_client):
    """Verify that live health check verification failure records failed deployment safely."""
    zip_buf = _create_zip_from_directory(CLEAN_APP_DIR)
    analyze_res = isolated_client.post(
        "/analyze",
        files={"file": ("clean-app.zip", zip_buf, "application/zip")},
    )
    run_id = analyze_res.json()["run_id"]

    mock_push_info = {
        "repo_url": "https://github.com/mock-user/clean-app",
        "clone_url": "https://github.com/mock-user/clean-app.git",
        "commit_sha": "clean01",
        "repo_name": "clean-app",
        "private": False,
    }

    mock_deploy_info = RenderDeployResult(
        service_id="srv-clean123",
        service_name="clean-app",
        repo_url="https://github.com/mock-user/clean-app",
        service_url="https://clean-app.onrender.com",
        live_url="https://clean-app.onrender.com",
        deploy_id="dep-clean456",
        status="live",
        created_at=1700000000.0,
    )

    failed_verification = VerificationResult(
        url="https://clean-app.onrender.com/health",
        healthy=False,
        status="http_500",
        http_status=500,
        error_message="HTTP 500 Internal Server Error",
    )

    failed_selffix = SelfFixResult(
        success=False,
        attempts_count=2,
        final_verification=failed_verification,
        history=[],
        live_url="https://clean-app.onrender.com",
        message="Live health check returned HTTP 500 after 2 attempts",
    )

    with patch("main.push_workspace_to_github", return_value=mock_push_info), \
         patch("main.deploy_project_to_render", return_value=mock_deploy_info), \
         patch("main.run_self_fix_loop", return_value=failed_selffix):

        approve_res = isolated_client.post(
            "/approve",
            json={"run_id": run_id, "approved_patch_ids": []},
        )
        assert approve_res.status_code == 200

    # History should contain failed deployment record
    history_res = isolated_client.get("/history")
    deployments = history_res.json()["deployments"]
    matching_deps = [d for d in deployments if d["analysis_id"] == run_id]
    assert len(matching_deps) == 1
    assert "Failed" in matching_deps[0]["health_status"]


# =========================================================================
# 4. MODEL CONFIGURATION SOURCE OF TRUTH CHECK
# =========================================================================

def test_model_configuration_source_of_truth(isolated_client):
    """Verify that backend configuration is the single source of truth for Gemini model name."""
    cfg = get_settings()
    connections_res = isolated_client.get("/connections")
    assert connections_res.status_code == 200
    conn_data = connections_res.json()
    assert conn_data["gemini"]["model"] == cfg.gemini_model

    settings_res = isolated_client.get("/settings")
    assert settings_res.status_code == 200
    set_data = settings_res.json()
    assert set_data["gemini_model"] == cfg.gemini_model
