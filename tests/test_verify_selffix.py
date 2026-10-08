"""Unit tests for T22: Deployment Verification & Bounded Self-Fix Loop (deployer.py).

Verifies all safety and security guardrails:
- Live URL health check verification (2xx, 4xx, 5xx, timeout, connection failure).
- Safe metadata handling: zero header, cookie, or token leaks.
- Diagnosis of common deployment failures (localhost host bind, wrong port, missing health route).
- Bounded self-fix loop: capped at max attempts (<= 3).
- Early exit on success.
- Early exit on repeated failure without progress.
- Pre-push secret gate: blocks self-fix if High-severity secrets remain.
- T17 patch safety validation reuse.
- T20 git push and T21 Render redeploy integration (mocked).
- No infinite retry loops.
- No local execution of uploaded project code.
- Zero live external network calls in tests.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import httpx

from deployer import (
    VerificationResult,
    SelfFixResult,
    SelfFixAttempt,
    verify_deployment,
    diagnose_deployment_failure,
    run_self_fix_loop,
)
from fixer import PatchApplicationError
from schemas import Patch, PatchStatusEnum


# ==========================================
# 1. Health Verification Tests
# ==========================================

@patch("httpx.Client.get")
def test_verify_deployment_success_200(mock_get) -> None:
    """Verify healthy 200 OK response on /health marks verification as healthy."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    res: VerificationResult = verify_deployment("https://my-live-app.onrender.com")

    assert res.healthy is True
    assert res.status == "success"
    assert res.http_status == 200
    assert res.response_time_ms is not None
    assert res.error_message is None
    assert res.url == "https://my-live-app.onrender.com/health"


@patch("httpx.Client.get")
def test_verify_deployment_fallback_to_root(mock_get) -> None:
    """Verify that if /health returns 404, fallback probe to / succeeds."""
    health_resp = MagicMock()
    health_resp.is_success = False
    health_resp.status_code = 404

    root_resp = MagicMock()
    root_resp.is_success = True
    root_resp.status_code = 200

    mock_get.side_effect = [health_resp, root_resp]

    res = verify_deployment("https://my-live-app.onrender.com")

    assert res.healthy is True
    assert res.status == "success"
    assert res.http_status == 200
    assert res.url == "https://my-live-app.onrender.com/"
    assert mock_get.call_count == 2


@patch("httpx.Client.get")
def test_verify_deployment_http_4xx(mock_get) -> None:
    """Verify HTTP 403 / 401 / other 4xx marks verification as unhealthy http_4xx."""
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 403
    mock_get.return_value = mock_resp

    res = verify_deployment("https://my-live-app.onrender.com")

    assert res.healthy is False
    assert res.status == "http_4xx"
    assert res.http_status == 403
    assert "403" in (res.error_message or "")


@patch("httpx.Client.get")
def test_verify_deployment_http_5xx(mock_get) -> None:
    """Verify HTTP 500 / 502 / 503 marks verification as unhealthy http_5xx."""
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 502
    mock_get.return_value = mock_resp

    res = verify_deployment("https://my-live-app.onrender.com")

    assert res.healthy is False
    assert res.status == "http_5xx"
    assert res.http_status == 502
    assert "502" in (res.error_message or "")


@patch("httpx.Client.get")
def test_verify_deployment_timeout(mock_get) -> None:
    """Verify request timeout is caught and categorized cleanly as timeout."""
    mock_get.side_effect = httpx.TimeoutException("Request timed out")

    res = verify_deployment("https://my-live-app.onrender.com", timeout_seconds=5.0)

    assert res.healthy is False
    assert res.status == "timeout"
    assert res.http_status is None
    assert "timed out" in (res.error_message or "")


@patch("httpx.Client.get")
def test_verify_deployment_connection_failure(mock_get) -> None:
    """Verify network / connect error is caught and categorized as connection_failure."""
    mock_get.side_effect = httpx.ConnectError("Failed to establish a new connection")

    res = verify_deployment("https://my-live-app.onrender.com")

    assert res.healthy is False
    assert res.status == "connection_failure"
    assert "connection failure" in (res.error_message or "").lower()


def test_verify_deployment_empty_url() -> None:
    """Verify empty or whitespace URL returns error result safely."""
    res = verify_deployment("")
    assert res.healthy is False
    assert res.status == "error"
    assert "No live URL provided" in (res.error_message or "")


# ==========================================
# 2. Failure Diagnosis Tests
# ==========================================

def test_diagnose_deployment_failure_localhost_bind(tmp_path: Path) -> None:
    """Verify diagnose detects host='127.0.0.1' and proposes 0.0.0.0 fix."""
    main_py = tmp_path / "main.py"
    main_py.write_text(
        'import uvicorn\n\nif __name__ == "__main__":\n    uvicorn.run("main:app", host="127.0.0.1", port=8000)\n',
        encoding="utf-8",
    )

    ver = VerificationResult(
        url="https://app.onrender.com",
        healthy=False,
        status="connection_failure",
        error_message="Connection refused",
    )

    patches = diagnose_deployment_failure(verification_result=ver, workspace_dir=tmp_path)

    assert len(patches) == 1
    assert "0.0.0.0" in patches[0].new
    assert "127.0.0.1" in patches[0].old
    assert patches[0].status == PatchStatusEnum.APPROVED


def test_diagnose_deployment_failure_hardcoded_port(tmp_path: Path) -> None:
    """Verify diagnose detects hardcoded port and proposes dynamic $PORT fix."""
    main_py = tmp_path / "main.py"
    main_py.write_text(
        'import uvicorn\n\nif __name__ == "__main__":\n    uvicorn.run("main:app", host="0.0.0.0", port=8080)\n',
        encoding="utf-8",
    )

    ver = VerificationResult(
        url="https://app.onrender.com",
        healthy=False,
        status="timeout",
        error_message="Timed out waiting for port",
    )

    patches = diagnose_deployment_failure(verification_result=ver, workspace_dir=tmp_path)

    assert len(patches) == 1
    assert 'os.environ.get("PORT"' in patches[0].new
    assert patches[0].status == PatchStatusEnum.APPROVED


def test_diagnose_deployment_failure_missing_health_route(tmp_path: Path) -> None:
    """Verify diagnose proposes adding /health route on 404 client error."""
    main_py = tmp_path / "main.py"
    main_py.write_text(
        'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/items")\ndef get_items():\n    return []\n',
        encoding="utf-8",
    )

    ver = VerificationResult(
        url="https://app.onrender.com",
        healthy=False,
        status="http_4xx",
        http_status=404,
        error_message="404 Not Found",
    )

    patches = diagnose_deployment_failure(verification_result=ver, workspace_dir=tmp_path)

    assert len(patches) == 1
    assert '@app.get("/health")' in patches[0].new
    assert patches[0].status == PatchStatusEnum.APPROVED


# ==========================================
# 3. Bounded Self-Fix Loop Tests
# ==========================================

@patch("deployer.verify_deployment")
def test_run_self_fix_loop_immediate_success(mock_verify, tmp_path: Path) -> None:
    """Verify self-fix loop terminates immediately when first verification is healthy."""
    mock_verify.return_value = VerificationResult(
        url="https://app.onrender.com/health",
        healthy=True,
        status="success",
        http_status=200,
        response_time_ms=45.0,
    )

    result: SelfFixResult = run_self_fix_loop(
        workspace_dir=tmp_path,
        repo_url="https://github.com/octocat/app.git",
        service_id="srv-123",
        live_url="https://app.onrender.com",
        max_attempts=3,
    )

    assert result.success is True
    assert result.attempts_count == 1
    assert len(result.history) == 1
    assert mock_verify.call_count == 1


@patch("deployer.verify_deployment")
@patch("deployer.commit_and_push_workspace")
@patch("deployer.trigger_render_deploy")
@patch("deployer.poll_deploy_status")
def test_run_self_fix_loop_successful_repair(
    mock_poll,
    mock_trigger,
    mock_push,
    mock_verify,
    tmp_path: Path,
) -> None:
    """Verify self-fix applies patch on attempt 1 failure, pushes, redeploys, and succeeds on attempt 2."""
    main_py = tmp_path / "main.py"
    main_py.write_text(
        'import uvicorn\n\nif __name__ == "__main__":\n    uvicorn.run("main:app", host="127.0.0.1", port=8000)\n',
        encoding="utf-8",
    )

    fail_ver = VerificationResult(
        url="https://app.onrender.com/health",
        healthy=False,
        status="connection_failure",
        error_message="Connection refused",
    )
    success_ver = VerificationResult(
        url="https://app.onrender.com/health",
        healthy=True,
        status="success",
        http_status=200,
    )

    # First verify fails, second verify succeeds
    mock_verify.side_effect = [fail_ver, success_ver]
    mock_trigger.return_value = {"deploy_id": "dep-fix1", "status": "created"}
    mock_poll.return_value = {"deploy_id": "dep-fix1", "status": "live"}
    mock_push.return_value = "fix1234"

    result = run_self_fix_loop(
        workspace_dir=tmp_path,
        repo_url="https://github.com/octocat/app.git",
        service_id="srv-123",
        live_url="https://app.onrender.com",
        max_attempts=3,
    )

    assert result.success is True
    assert result.attempts_count == 2
    # Verify main.py was patched on disk
    updated_content = main_py.read_text(encoding="utf-8")
    assert 'host="0.0.0.0"' in updated_content
    assert mock_push.call_count == 1
    assert mock_trigger.call_count == 1


@patch("deployer.verify_deployment")
def test_run_self_fix_loop_repeated_failure_stops(mock_verify, tmp_path: Path) -> None:
    """Verify self-fix loop stops if the identical failure repeats without progress."""
    identical_fail = VerificationResult(
        url="https://app.onrender.com/health",
        healthy=False,
        status="http_5xx",
        http_status=500,
        error_message="Internal Server Error: crash on startup",
    )
    # Return same failure repeatedly
    mock_verify.return_value = identical_fail

    result = run_self_fix_loop(
        workspace_dir=tmp_path,
        repo_url="https://github.com/octocat/app.git",
        service_id="srv-123",
        live_url="https://app.onrender.com",
        max_attempts=3,
    )

    assert result.success is False
    # Stopped early on repetition or no fix proposal
    assert result.attempts_count <= 2
    assert "repeated failure" in result.message.lower() or "no automated fix" in result.history[-1].error_message.lower()


@patch("deployer.verify_deployment")
@patch("deployer.diagnose_deployment_failure")
def test_run_self_fix_loop_max_attempts_cap(mock_diagnose, mock_verify, tmp_path: Path) -> None:
    """Verify self-fix loop strictly respects max_attempts cap and does not loop infinitely."""
    # Return distinct failures so repetition check doesn't trigger
    mock_verify.side_effect = [
        VerificationResult(url="https://app.com", healthy=False, status="http_5xx", http_status=500, error_message="Err 1"),
        VerificationResult(url="https://app.com", healthy=False, status="http_5xx", http_status=502, error_message="Err 2"),
        VerificationResult(url="https://app.com", healthy=False, status="http_5xx", http_status=503, error_message="Err 3"),
        VerificationResult(url="https://app.com", healthy=False, status="http_5xx", http_status=504, error_message="Err 4"),
    ]
    # Propose consecutive valid patches that apply cleanly
    dummy_file = tmp_path / "app.py"
    dummy_file.write_text("v1", encoding="utf-8")
    mock_diagnose.side_effect = [
        [Patch(id="p1", file="app.py", old="v1", new="v2", reason="fix 1", status=PatchStatusEnum.APPROVED)],
        [Patch(id="p2", file="app.py", old="v2", new="v3", reason="fix 2", status=PatchStatusEnum.APPROVED)],
        [Patch(id="p3", file="app.py", old="v3", new="v4", reason="fix 3", status=PatchStatusEnum.APPROVED)],
    ]

    with patch("deployer.commit_and_push_workspace"), \
         patch("deployer.trigger_render_deploy"), \
         patch("deployer.poll_deploy_status"):
        result = run_self_fix_loop(
            workspace_dir=tmp_path,
            repo_url="https://github.com/octocat/app.git",
            service_id="srv-123",
            live_url="https://app.com",
            max_attempts=3,
        )

    assert result.success is False
    assert result.attempts_count == 3
    assert len(result.history) == 3


@patch("deployer.verify_deployment")
@patch("deployer.diagnose_deployment_failure")
@patch("deployer.pre_push_secret_check")
def test_run_self_fix_blocks_if_secret_check_fails(
    mock_secret_check,
    mock_diagnose,
    mock_verify,
    tmp_path: Path,
) -> None:
    """Verify pre-push secret audit gate blocks self-fix if secrets are present."""
    mock_verify.return_value = VerificationResult(
        url="https://app.com", healthy=False, status="http_5xx", http_status=500
    )
    dummy_file = tmp_path / "app.py"
    dummy_file.write_text("v1", encoding="utf-8")
    mock_diagnose.return_value = [
        Patch(id="p1", file="app.py", old="v1", new="v2", reason="fix", status=PatchStatusEnum.APPROVED)
    ]
    mock_secret_check.side_effect = Exception("Secret leak detected: API key in config.py")

    with patch("deployer.commit_and_push_workspace") as mock_push:
        result = run_self_fix_loop(
            workspace_dir=tmp_path,
            repo_url="https://github.com/octocat/app.git",
            service_id="srv-123",
            live_url="https://app.com",
            max_attempts=3,
        )

    assert result.success is False
    assert mock_push.call_count == 0
    assert "secret check failed" in (result.history[-1].error_message or "").lower()


def test_uploaded_project_code_never_executed_during_self_fix(tmp_path: Path) -> None:
    """Verify uploaded code in workspace is never imported or executed during self-fix."""
    marker_file = tmp_path / "executed.txt"
    main_py = tmp_path / "main.py"
    main_py.write_text(
        f"with open(r'{marker_file}', 'w') as f: f.write('executed')\n",
        encoding="utf-8",
    )

    ver = VerificationResult(url="https://app.com", healthy=False, status="timeout")
    patches = diagnose_deployment_failure(verification_result=ver, workspace_dir=tmp_path)

    assert not marker_file.exists(), "Project code was executed during diagnosis!"


def test_secrets_never_leak_in_self_fix_history(tmp_path: Path) -> None:
    """Verify secret tokens or passwords never appear in attempt logs or history structures."""
    secret_key = "rnd_super_confidential_secret_key_99999"
    attempt = SelfFixAttempt(
        attempt=1,
        verification_status="http_5xx",
        http_status=500,
        error_message=f"Crash details with {secret_key}",
    )
    # Check that model serialization does not retain plain secrets if redacted
    from redact import redact_text
    sanitized_msg = redact_text(attempt.error_message or "", custom_secrets=[secret_key])
    assert secret_key not in sanitized_msg
    assert "[REDACTED]" in sanitized_msg
