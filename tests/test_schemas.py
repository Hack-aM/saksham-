"""Unit tests for Pydantic schema validation in schemas.py."""

import pytest
from pydantic import ValidationError
from schemas import (
    Issue,
    Patch,
    AnalysisResult,
    DeployResult,
    SeverityEnum,
    PatchStatusEnum,
)


def test_valid_issue() -> None:
    """Verify that a properly structured Issue passes validation."""
    issue = Issue(
        severity=SeverityEnum.HIGH,
        title="Hardcoded API Key",
        file="config.py",
        line=12,
        explanation="Secret key exposed in code.",
    )
    assert issue.severity == SeverityEnum.HIGH
    assert issue.title == "Hardcoded API Key"
    assert issue.file == "config.py"
    assert issue.line == 12


def test_invalid_issue_severity_rejected() -> None:
    """Verify that invalid severity values (e.g. Critical, Info) are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Issue(
            severity="Critical",  # Invalid severity
            title="Secret",
            file="config.py",
            line=1,
            explanation="Explanation",
        )
    assert "Input should be 'High', 'Medium' or 'Low'" in str(exc_info.value)


def test_valid_patch() -> None:
    """Verify that a valid Patch passes validation."""
    patch = Patch(
        file="config.py",
        old='API_KEY = "secret"',
        new='API_KEY = os.getenv("API_KEY")',
        reason="Move key to environment variable",
    )
    assert patch.status == PatchStatusEnum.SUGGESTED
    assert patch.old == 'API_KEY = "secret"'
    assert patch.new == 'API_KEY = os.getenv("API_KEY")'


def test_valid_analysis_result() -> None:
    """Verify that an AnalysisResult with nested issues and patches passes validation."""
    issue = Issue(
        severity=SeverityEnum.MEDIUM,
        title="Debug mode on",
        file="config.py",
        line=7,
        explanation="Debug should be disabled in production.",
    )
    patch = Patch(
        file="config.py",
        old="DEBUG = True",
        new="DEBUG = False",
        reason="Disable debug in production",
    )
    analysis = AnalysisResult(
        project_name="StudentApp",
        stack="Python / FastAPI",
        score=85,
        issues=[issue],
        patches=[patch],
    )
    assert analysis.project_name == "StudentApp"
    assert analysis.score == 85
    assert len(analysis.issues) == 1
    assert len(analysis.patches) == 1


def test_analysis_result_negative_score_rejected() -> None:
    """Verify that a score below 0 is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        AnalysisResult(
            project_name="BrokenApp",
            stack="Python",
            score=-10,  # Invalid: score < 0
        )
    assert "greater than or equal to 0" in str(exc_info.value)


def test_analysis_result_score_above_100_rejected() -> None:
    """Verify that a score above 100 is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        AnalysisResult(
            project_name="OverScoreApp",
            stack="Python",
            score=110,  # Invalid: score > 100
        )
    assert "less than or equal to 100" in str(exc_info.value)


def test_valid_deploy_result() -> None:
    """Verify that a DeployResult with valid platform and health status passes validation."""
    res = DeployResult(
        analysis_id="an-123",
        repo_url="https://github.com/user/app",
        live_url="https://app.onrender.com",
        health_status="200 OK",
        final_score=95,
        logs="Build successful.",
    )
    assert res.platform == "Render"
    assert res.final_score == 95
    assert res.health_status == "200 OK"


def test_deploy_result_invalid_score_rejected() -> None:
    """Verify that invalid final_score on DeployResult is rejected."""
    with pytest.raises(ValidationError):
        DeployResult(
            analysis_id="an-123",
            repo_url="https://github.com/user/app",
            live_url="https://app.onrender.com",
            health_status="200 OK",
            final_score=150,  # Invalid
        )
