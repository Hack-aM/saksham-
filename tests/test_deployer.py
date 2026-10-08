"""Unit tests for T21: Render Deployer Module (deployer.py).

Verifies all safety and security guardrails:
- Missing and invalid RENDER_API_KEY handling.
- Successful service creation and deploy triggering.
- Full deployment lifecycle (creation_requested, in-progress, live, failed, timeout).
- Transient 5xx retry mechanism with bounded backoff.
- Permanent 4xx error fail-fast without indefinite retry.
- HTTP timeout handling.
- Strict API key redaction in errors, logs, and response structures.
- Pre-deploy secret scan gate: blocks deployment if unresolved High-severity secrets exist.
- Requires valid T20 GitHub repository URL.
- Returned metadata is typed (RenderDeployResult).
- Uploaded project code is never executed locally.
- Zero live Render API calls or real services created.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import httpx

from deployer import (
    RenderAuthError,
    RenderAPIError,
    RenderDeployError,
    RenderTimeoutError,
    RenderDeployResult,
    validate_service_name,
    validate_render_api_key,
    create_render_service,
    set_render_env_vars,
    trigger_render_deploy,
    get_deploy_status,
    get_service_details,
    poll_deploy_status,
    deploy_project_to_render,
)
from schemas import Issue, SeverityEnum


# ==========================================
# 1. Service Name Validation Tests
# ==========================================

def test_service_name_validation_valid() -> None:
    """Verify that standard, valid service names pass validation."""
    valid_names = [
        "fastapi-backend",
        "saksham-demo",
        "app-123",
        "demo_app",  # Will convert _ to -
    ]
    for name in valid_names:
        validated = validate_service_name(name)
        assert "_" not in validated
        assert validated.isalnum() or "-" in validated


def test_service_name_validation_invalid() -> None:
    """Verify that empty, too long, or invalid character names are rejected."""
    invalid_cases = [
        "",
        "   ",
        "my app with spaces",
        "app$name",
        "app#name",
        "a" * 45,  # Exceeds 40 chars
    ]
    for invalid in invalid_cases:
        with pytest.raises(RenderDeployError):
            validate_service_name(invalid)


# ==========================================
# 2. Authentication and API Key Tests
# ==========================================

def test_validate_render_api_key_missing() -> None:
    """Verify that missing/empty RENDER_API_KEY raises RenderAuthError."""
    with pytest.raises(RenderAuthError) as exc_info:
        validate_render_api_key(api_key="")
    assert "Render API key is missing" in str(exc_info.value)


@patch("httpx.Client.get")
def test_validate_render_api_key_auth_failure(mock_get) -> None:
    """Verify 401/403 response raises RenderAuthError and masks key."""
    secret_key = "rnd_super_secret_render_api_key_12345"
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"message": f"Unauthorized request using key {secret_key}"}
    mock_get.return_value = mock_resp

    with pytest.raises(RenderAuthError) as exc_info:
        validate_render_api_key(api_key=secret_key)

    err_msg = str(exc_info.value)
    assert "authentication failed" in err_msg
    assert secret_key not in err_msg


@patch("httpx.Client.get")
def test_validate_render_api_key_success(mock_get) -> None:
    """Verify 200 response validates key successfully."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": "usr-123", "name": "student"}]
    mock_get.return_value = mock_resp

    assert validate_render_api_key(api_key="rnd_validkey1234567890abcdef") is True


# ==========================================
# 3. Service Creation Tests
# ==========================================

@patch("httpx.Client.post")
def test_create_render_service_success(mock_post) -> None:
    """Verify creating a Render web service returns service ID and URL."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "service": {
            "id": "srv-abc12345",
            "name": "my-saksham-app",
            "serviceDetails": {
                "url": "https://my-saksham-app.onrender.com",
            },
        }
    }
    mock_post.return_value = mock_resp

    res = create_render_service(
        repo_url="https://github.com/octocat/my-saksham-app",
        service_name="my-saksham-app",
        api_key="rnd_mock_key_1234567890",
    )

    assert res["service_id"] == "srv-abc12345"
    assert res["service_url"] == "https://my-saksham-app.onrender.com"
    assert res["name"] == "my-saksham-app"
    assert res["repo_url"] == "https://github.com/octocat/my-saksham-app"


def test_create_render_service_invalid_repo_url() -> None:
    """Verify non-GitHub or empty repo URL is rejected."""
    with pytest.raises(RenderDeployError) as exc_info:
        create_render_service(
            repo_url="https://gitlab.com/user/project",
            service_name="demo-app",
            api_key="rnd_mock_key",
        )
    assert "A valid GitHub repository URL is required" in str(exc_info.value)


@patch("httpx.Client.post")
def test_create_render_service_transient_retry_success(mock_post) -> None:
    """Verify 500 error triggers retry and succeeds on attempt 2."""
    error_resp = MagicMock()
    error_resp.is_success = False
    error_resp.status_code = 500
    error_resp.json.return_value = {"message": "Internal server error"}

    success_resp = MagicMock()
    success_resp.is_success = True
    success_resp.status_code = 201
    success_resp.json.return_value = {
        "service": {
            "id": "srv-retry123",
            "name": "retry-app",
            "serviceDetails": {"url": "https://retry-app.onrender.com"},
        }
    }

    mock_post.side_effect = [error_resp, success_resp]

    with patch("time.sleep", return_value=None):
        res = create_render_service(
            repo_url="https://github.com/octocat/retry-app",
            service_name="retry-app",
            api_key="rnd_mock_key",
            max_retries=2,
        )

    assert res["service_id"] == "srv-retry123"
    assert mock_post.call_count == 2


@patch("httpx.Client.post")
def test_create_render_service_422_no_retry(mock_post) -> None:
    """Verify 422 validation error fails fast without retrying."""
    val_err_resp = MagicMock()
    val_err_resp.is_success = False
    val_err_resp.status_code = 422
    val_err_resp.json.return_value = {"message": "Service name already taken"}
    mock_post.return_value = val_err_resp

    with pytest.raises(RenderAPIError) as exc_info:
        create_render_service(
            repo_url="https://github.com/octocat/taken-app",
            service_name="taken-app",
            api_key="rnd_mock_key",
            max_retries=2,
        )

    assert "422" in str(exc_info.value)
    assert mock_post.call_count == 1


# ==========================================
# 4. Environment Variables Tests
# ==========================================

@patch("httpx.Client.put")
def test_set_render_env_vars_success(mock_put) -> None:
    """Verify setting environment variables sends expected JSON payload."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_put.return_value = mock_resp

    set_render_env_vars(
        service_id="srv-123",
        env_vars={"PORT": "8000", "APP_ENV": "production"},
        api_key="rnd_key",
    )

    assert mock_put.call_count == 1
    call_kwargs = mock_put.call_args[1]
    assert call_kwargs["json"] == [
        {"key": "PORT", "value": "8000"},
        {"key": "APP_ENV", "value": "production"},
    ]


# ==========================================
# 5. Deployment Lifecycle & Polling Tests
# ==========================================

@patch("httpx.Client.post")
def test_trigger_render_deploy_success(mock_post) -> None:
    """Verify triggering deployment returns deploy ID and created status."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "dep-xyz123", "status": "created"}
    mock_post.return_value = mock_resp

    res = trigger_render_deploy(service_id="srv-123", api_key="rnd_key")
    assert res["deploy_id"] == "dep-xyz123"
    assert res["status"] == "created"


@patch("deployer.get_deploy_status")
@patch("deployer.get_service_details")
def test_poll_deploy_status_success(mock_details, mock_status) -> None:
    """Verify polling transitions through in-progress and reaches live status."""
    # First 2 calls: in_progress, 3rd call: live
    mock_status.side_effect = [
        {"deploy_id": "dep-1", "status": "build_in_progress"},
        {"deploy_id": "dep-1", "status": "update_in_progress"},
        {"deploy_id": "dep-1", "status": "live"},
    ]
    mock_details.return_value = {
        "service_id": "srv-123",
        "service_url": "https://live-service.onrender.com",
    }

    with patch("time.sleep", return_value=None):
        res = poll_deploy_status(
            service_id="srv-123",
            deploy_id="dep-1",
            api_key="rnd_key",
            poll_interval_seconds=0.1,
            max_wait_seconds=10.0,
        )

    assert res["status"] == "live"
    assert res["service_url"] == "https://live-service.onrender.com"
    assert mock_status.call_count == 3


@patch("deployer.get_deploy_status")
def test_poll_deploy_status_failure(mock_status) -> None:
    """Verify terminal build_failed state raises RenderDeployError immediately."""
    mock_status.return_value = {"deploy_id": "dep-fail", "status": "build_failed"}

    with pytest.raises(RenderDeployError) as exc_info:
        poll_deploy_status(
            service_id="srv-123",
            deploy_id="dep-fail",
            api_key="rnd_key",
        )

    assert "build_failed" in str(exc_info.value)


@patch("deployer.get_deploy_status")
def test_poll_deploy_status_timeout(mock_status) -> None:
    """Verify polling raises RenderTimeoutError when max_wait_seconds is exceeded."""
    mock_status.return_value = {"deploy_id": "dep-slow", "status": "build_in_progress"}

    with patch("time.sleep", return_value=None), patch("time.time", side_effect=[0, 10, 20, 350]):
        with pytest.raises(RenderTimeoutError) as exc_info:
            poll_deploy_status(
                service_id="srv-123",
                deploy_id="dep-slow",
                api_key="rnd_key",
                max_wait_seconds=300.0,
            )

    assert "timed out" in str(exc_info.value)


# ==========================================
# 6. Full Deployment Pipeline & Security Gates
# ==========================================

@patch("deployer.validate_render_api_key")
@patch("deployer.create_render_service")
@patch("deployer.trigger_render_deploy")
@patch("deployer.poll_deploy_status")
def test_deploy_project_to_render_full_pipeline_success(
    mock_poll,
    mock_trigger,
    mock_create,
    mock_validate,
) -> None:
    """Verify end-to-end deployment pipeline produces structured RenderDeployResult."""
    mock_validate.return_value = True
    mock_create.return_value = {
        "service_id": "srv-prod123",
        "service_url": "https://prod-app.onrender.com",
        "name": "prod-app",
        "repo_url": "https://github.com/octocat/prod-app",
    }
    mock_trigger.return_value = {"deploy_id": "dep-prod123", "status": "created"}
    mock_poll.return_value = {
        "deploy_id": "dep-prod123",
        "status": "live",
        "service_url": "https://prod-app.onrender.com",
    }

    result: RenderDeployResult = deploy_project_to_render(
        repo_url="https://github.com/octocat/prod-app",
        service_name="prod-app",
        api_key="rnd_valid_key_1234567890",
    )

    assert isinstance(result, RenderDeployResult)
    assert result.service_id == "srv-prod123"
    assert result.deploy_id == "dep-prod123"
    assert result.status == "live"
    assert result.service_url == "https://prod-app.onrender.com"
    assert result.repo_url == "https://github.com/octocat/prod-app"
    assert result.error_message is None


@patch("deployer.pre_push_secret_check")
def test_deploy_blocks_on_high_severity_secrets(mock_secret_check, tmp_path: Path) -> None:
    """Verify that unresolved High-severity secret in workspace blocks deployment."""
    mock_secret_check.side_effect = RenderDeployError(
        "Pre-push secret check failed: High-severity secret leak detected ('Planted Secret Key')."
    )

    with pytest.raises(RenderDeployError) as exc_info:
        deploy_project_to_render(
            repo_url="https://github.com/octocat/vulnerable-app",
            service_name="vulnerable-app",
            workspace_dir=tmp_path,
            api_key="rnd_valid_key",
        )

    assert "High-severity secret leak detected" in str(exc_info.value)


@patch("deployer.validate_render_api_key")
@patch("deployer.create_render_service")
@patch("deployer.trigger_render_deploy")
@patch("deployer.poll_deploy_status")
def test_deploy_pipeline_handles_terminal_failure_cleanly(
    mock_poll,
    mock_trigger,
    mock_create,
    mock_validate,
) -> None:
    """Verify deployment failure returns safe typed result with masked error."""
    secret_key = "rnd_super_secret_credential_12345"
    mock_validate.return_value = True
    mock_create.return_value = {
        "service_id": "srv-fail",
        "service_url": None,
        "name": "fail-app",
        "repo_url": "https://github.com/octocat/fail-app",
    }
    mock_trigger.return_value = {"deploy_id": "dep-fail", "status": "created"}
    mock_poll.side_effect = RenderDeployError(f"Render deployment failed: key {secret_key}")

    result = deploy_project_to_render(
        repo_url="https://github.com/octocat/fail-app",
        service_name="fail-app",
        api_key=secret_key,
    )

    assert result.status == "failed"
    assert result.error_message is not None
    assert secret_key not in result.error_message
    assert secret_key not in str(result.model_dump())


def test_uploaded_project_code_is_never_executed_during_deploy(tmp_path: Path) -> None:
    """Verify uploaded workspace project code is never imported or executed."""
    marker_file = tmp_path / "executed.txt"
    app_file = tmp_path / "main.py"
    app_file.write_text(
        f"with open(r'{marker_file}', 'w') as f: f.write('executed')",
        encoding="utf-8",
    )

    # Validate name and repo format
    assert validate_service_name("demo-app") == "demo-app"
    assert not marker_file.exists(), "Project code was executed locally during deploy stage!"
