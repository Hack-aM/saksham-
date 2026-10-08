"""Tests for /history, /connections, and /settings endpoints (T28)."""

import pytest
from fastapi.testclient import TestClient
from main import app
from db import init_db, save_analysis, save_deployment


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup clean isolated SQLite database for test session."""
    test_db = tmp_path / "test_saksham.db"
    init_db(str(test_db))
    monkeypatch.setattr("db.get_db_path", lambda custom_path=None: str(test_db))
    return str(test_db)


def test_history_endpoint_empty(setup_test_db):
    """Test GET /history when database is empty."""
    client = TestClient(app)
    response = client.get("/history")
    assert response.status_code == 200
    data = response.json()
    assert "analyses" in data
    assert "deployments" in data
    assert len(data["analyses"]) == 0
    assert len(data["deployments"]) == 0


def test_history_endpoint_populated(setup_test_db):
    """Test GET /history returns saved analyses and deployments."""
    analysis_id = save_analysis(
        project_name="demo-fastapi-service",
        stack="Python / FastAPI (Port 8000)",
        score=95,
        issues=[
            {
                "id": "iss-1",
                "severity": "Medium",
                "title": "Port hardcoded",
                "file": "main.py",
                "line": 15,
                "explanation": "Port 8000 hardcoded in app.",
            }
        ],
        patches=[],
    )

    save_deployment(
        analysis_id=analysis_id,
        repo_url="https://github.com/user/demo-fastapi-service",
        live_url="https://demo-fastapi-service.onrender.com",
        platform="Render",
        health_status="200 OK",
        final_score=95,
        logs="Deployment healthy",
    )

    client = TestClient(app)
    response = client.get("/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data["analyses"]) == 1
    assert data["analyses"][0]["project_name"] == "demo-fastapi-service"
    assert len(data["deployments"]) == 1
    assert data["deployments"][0]["live_url"] == "https://demo-fastapi-service.onrender.com"


def test_connections_endpoint_safe_metadata():
    """Test GET /connections returns integration statuses without exposing secret keys."""
    client = TestClient(app)
    response = client.get("/connections")
    assert response.status_code == 200
    data = response.json()

    assert "gemini" in data
    assert "github" in data
    assert "render" in data

    # Ensure no secret strings or tokens are leaked in the response
    for key, val in data.items():
        assert "configured" in val
        assert "name" in val
        assert "description" in val
        # Ensure raw secret values are NEVER present
        assert "api_key" not in val
        assert "token" not in val


def test_settings_endpoint_safe_metadata():
    """Test GET /settings returns non-sensitive operational settings."""
    client = TestClient(app)
    response = client.get("/settings")
    assert response.status_code == 200
    data = response.json()

    assert "environment" in data
    assert "max_upload_size_mb" in data
    assert "workspace_ttl_seconds" in data
    assert "default_platform" in data
    assert data["default_platform"] == "Render"
    assert "score_deductions" in data
    assert data["score_deductions"]["high"] == 30
    assert data["score_deductions"]["medium"] == 15
    assert data["score_deductions"]["low"] == 5
