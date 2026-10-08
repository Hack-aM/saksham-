"""Unit tests for SQLite persistence in db.py."""

from pathlib import Path
import pytest
from db import (
    init_db,
    save_analysis,
    get_analysis,
    list_analyses,
    save_deployment,
    get_deployment,
    list_deployments,
    update_patch_status,
)


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    """Fixture providing an isolated temporary SQLite database path."""
    db_file = tmp_path / "test_saksham.db"
    init_db(str(db_file))
    return str(db_file)


def test_init_db_creates_tables(test_db_path: str) -> None:
    """Verify that tables are created and can be queried without error."""
    analyses = list_analyses(db_path=test_db_path)
    assert analyses == []


def test_save_and_get_analysis(test_db_path: str) -> None:
    """Verify saving an analysis with issues and patches, then retrieving it."""
    issues = [
        {
            "id": "iss-1",
            "severity": "High",
            "title": "Hardcoded API Key",
            "file": "config.py",
            "line": 12,
            "explanation": "Production credential found in code",
        },
        {
            "id": "iss-2",
            "severity": "Medium",
            "title": "Port hardcoded",
            "file": "main.py",
            "line": 18,
            "explanation": "Should use PORT env var",
        },
    ]
    patches = [
        {
            "id": "patch-1",
            "issue_id": "iss-1",
            "file": "config.py",
            "old": "API_KEY = 'secret'",
            "new": "API_KEY = os.getenv('API_KEY')",
            "reason": "Move key to environment variable",
            "status": "suggested",
        }
    ]

    analysis_id = save_analysis(
        project_name="DemoApp",
        stack="Python / FastAPI",
        score=40,
        issues=issues,
        patches=patches,
        db_path=test_db_path,
    )
    assert analysis_id is not None

    retrieved = get_analysis(analysis_id, db_path=test_db_path)
    assert retrieved is not None
    assert retrieved["project_name"] == "DemoApp"
    assert retrieved["score"] == 40
    assert len(retrieved["issues"]) == 2
    assert retrieved["issues"][0]["title"] == "Hardcoded API Key"
    assert len(retrieved["patches"]) == 1
    assert retrieved["patches"][0]["status"] == "suggested"


def test_update_patch_status(test_db_path: str) -> None:
    """Verify updating patch status from suggested to approved/applied."""
    patches = [
        {
            "id": "patch-status-test",
            "file": "config.py",
            "old": "a=1",
            "new": "a=2",
            "reason": "Update",
            "status": "suggested",
        }
    ]
    analysis_id = save_analysis(
        project_name="PatchApp",
        stack="Python",
        score=50,
        issues=[],
        patches=patches,
        db_path=test_db_path,
    )

    success = update_patch_status("patch-status-test", "approved", db_path=test_db_path)
    assert success is True

    analysis = get_analysis(analysis_id, db_path=test_db_path)
    assert analysis is not None
    assert analysis["patches"][0]["status"] == "approved"


def test_save_and_list_deployments(test_db_path: str) -> None:
    """Verify saving deployments and retrieving them via list_deployments."""
    analysis_id = save_analysis(
        project_name="DeployTestApp",
        stack="Python / FastAPI",
        score=40,
        issues=[],
        patches=[],
        db_path=test_db_path,
    )

    deploy_id = save_deployment(
        analysis_id=analysis_id,
        repo_url="https://github.com/user/demo-repo",
        live_url="https://demo-app.onrender.com",
        platform="Render",
        health_status="200 OK",
        final_score=95,
        logs="Building... Deployed successfully. Health check passed.",
        db_path=test_db_path,
    )

    deployment = get_deployment(deploy_id, db_path=test_db_path)
    assert deployment is not None
    assert deployment["repo_url"] == "https://github.com/user/demo-repo"
    assert deployment["live_url"] == "https://demo-app.onrender.com"
    assert deployment["final_score"] == 95

    deploy_list = list_deployments(db_path=test_db_path)
    assert len(deploy_list) == 1
    assert deploy_list[0]["project_name"] == "DeployTestApp"
    assert deploy_list[0]["initial_score"] == 40
    assert deploy_list[0]["final_score"] == 95


def test_database_redacts_secrets_in_raw_file(test_db_path: str) -> None:
    """Verify that sensitive API keys are masked before writing to SQLite so the raw DB file contains no secrets."""
    secret_key = "sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI"
    
    issues = [
        {
            "id": "iss-secret",
            "severity": "High",
            "title": f"Hardcoded API Key {secret_key}",
            "file": "config.py",
            "line": 12,
            "explanation": f"Found sensitive secret key {secret_key} in source code",
        }
    ]
    patches = [
        {
            "id": "patch-secret",
            "file": "config.py",
            "old": f'API_KEY = "{secret_key}"',
            "new": 'API_KEY = os.getenv("API_KEY")',
            "reason": f"Replace leaked key {secret_key} with os.getenv",
            "status": "suggested",
        }
    ]

    analysis_id = save_analysis(
        project_name="SecretLeakApp",
        stack="Python / FastAPI",
        score=20,
        issues=issues,
        patches=patches,
        db_path=test_db_path,
    )

    save_deployment(
        analysis_id=analysis_id,
        repo_url="https://github.com/user/secret-repo",
        live_url="https://secret-app.onrender.com",
        platform="Render",
        health_status="200 OK",
        final_score=95,
        logs=f"Deploy completed. Auth header with token {secret_key} used.",
        db_path=test_db_path,
    )

    # Read the raw SQLite binary file from disk
    raw_db_bytes = Path(test_db_path).read_bytes()
    
    # Assert the raw secret key string appears NOWHERE in the SQLite database file
    assert secret_key.encode("utf-8") not in raw_db_bytes
    assert b"sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI" not in raw_db_bytes
