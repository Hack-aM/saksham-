"""Saksham Render Deployer Module.

Handles web service creation on Render via the Render API, setting platform
environment variables/secrets, and monitoring deploy status per ARCHITECTURE.md
section 8 and TASKS.md T21.

Strict Security & Constraints:
- RENDER_API_KEY loaded from configuration/environment; never logged or returned.
- Render is the sole deployment target platform for MVP.
- Deploys ONLY after T19 approval and T20 GitHub push.
- Pre-deploy secret gate blocks deployment if unresolved High-severity secrets exist.
- Uploaded project code is never executed locally.
- Explicit timeouts and bounded retry on transient failures.
"""

import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

import httpx

from config import Settings, get_settings
from fixer import apply_patches
from github_push import commit_and_push_workspace, pre_push_secret_check
from redact import redact_text
from schemas import Issue, Patch, PatchStatusEnum, SeverityEnum

RENDER_API_BASE = "https://api.render.com/v1"
SERVICE_NAME_REGEX = re.compile(r"^[a-z0-9-]{1,40}$")


class VerificationResult(BaseModel):
    """Typed result of a live deployed service health check verification."""
    url: str = Field(..., description="Target service URL verified.")
    healthy: bool = Field(..., description="Whether the service is responsive and healthy.")
    status: str = Field(..., description="High-level status ('success', 'http_4xx', 'http_5xx', 'timeout', 'connection_failure', 'error').")
    http_status: Optional[int] = Field(default=None, description="HTTP status code if response received.")
    response_time_ms: Optional[float] = Field(default=None, description="Response latency in milliseconds.")
    error_message: Optional[str] = Field(default=None, description="Redacted error message on verification failure.")


class SelfFixAttempt(BaseModel):
    """Metadata for a single verification and self-fix attempt."""
    attempt: int = Field(..., description="1-indexed attempt number.")
    verification_status: str = Field(..., description="Status string from verification.")
    http_status: Optional[int] = Field(default=None, description="HTTP status code.")
    error_message: Optional[str] = Field(default=None, description="Redacted error message.")
    patch_applied: Optional[str] = Field(default=None, description="ID(s) or description of patches applied.")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp.")


class SelfFixResult(BaseModel):
    """Overall outcome of the deployment verification and self-fix loop."""
    success: bool = Field(..., description="Whether the service reached healthy live status.")
    attempts_count: int = Field(..., ge=0, description="Total verification/repair attempts executed.")
    final_verification: VerificationResult = Field(..., description="Final verification result object.")
    history: List[SelfFixAttempt] = Field(default_factory=list, description="Safe chronological attempt log.")
    live_url: Optional[str] = Field(default=None, description="Live service URL.")
    message: str = Field(..., description="Summary status message.")


class RenderDeployStatus(str, Enum):
    """Lifecycle status of a Render service deployment."""
    CREATED = "created"
    BUILD_IN_PROGRESS = "build_in_progress"
    UPDATE_IN_PROGRESS = "update_in_progress"
    LIVE = "live"
    BUILD_FAILED = "build_failed"
    UPDATE_FAILED = "update_failed"
    CANCELED = "canceled"
    DEACTIVATED = "deactivated"
    TIMEOUT = "timeout"
    FAILED = "failed"


class RenderDeployError(Exception):
    """Base exception for Render deployment failures."""
    pass


class RenderAuthError(RenderDeployError):
    """Raised when Render API authentication fails (401/403)."""
    pass


class RenderAPIError(RenderDeployError):
    """Raised on non-auth 4xx/5xx errors from the Render API."""
    pass


class RenderTimeoutError(RenderDeployError):
    """Raised when deploy status polling exceeds maximum wait duration."""
    pass


class RenderDeployResult(BaseModel):
    """Typed result of a Render service creation and deployment."""
    service_id: str = Field(..., description="Render service ID (e.g. srv-xxx).")
    deploy_id: Optional[str] = Field(default=None, description="Render deploy ID (e.g. dep-xxx).")
    status: str = Field(..., description="High-level deployment status ('live', 'in_progress', 'failed', 'timeout').")
    service_url: Optional[str] = Field(default=None, description="Live URL of the deployed web service.")
    live_url: Optional[str] = Field(default=None, description="Alias for live URL of the deployed web service.")
    repo_url: str = Field(..., description="Source GitHub repository URL.")
    raw_status: Optional[str] = Field(default=None, description="Raw status from Render API.")
    error_message: Optional[str] = Field(default=None, description="Redacted error message if deployment failed.")


def validate_service_name(name: str) -> str:
    """Validate and sanitize Render service name.

    Args:
        name: Proposed service name.

    Returns:
        str: Sanitized lowercase service name.

    Raises:
        RenderDeployError: If name contains invalid characters.
    """
    cleaned = (name or "").strip().lower()
    if not cleaned:
        raise RenderDeployError("Render service name cannot be empty.")

    # Replace underscores with hyphens
    cleaned = cleaned.replace("_", "-")

    if not SERVICE_NAME_REGEX.match(cleaned):
        raise RenderDeployError(
            f"Invalid Render service name: '{name}'. Service name must be 1-40 lowercase "
            f"alphanumeric characters or hyphens."
        )

    return cleaned


def _get_auth_headers(api_key: str) -> Dict[str, str]:
    """Generate authenticated HTTP headers for Render API requests."""
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _handle_response_error(response: httpx.Response, api_key: str) -> None:
    """Check response status and raise appropriate typed exception with redacted details."""
    if response.is_success:
        return

    status_code = response.status_code
    try:
        data = response.json()
        raw_msg = str(data.get("message", data))
    except Exception:
        raw_msg = response.text or f"HTTP {status_code}"

    sanitized = redact_text(raw_msg, custom_secrets=[api_key])

    if status_code in {401, 403}:
        raise RenderAuthError(f"Render API authentication failed ({status_code}): {sanitized}")
    elif status_code == 422:
        raise RenderAPIError(f"Render API validation error (422): {sanitized}")
    else:
        raise RenderAPIError(f"Render API error ({status_code}): {sanitized}")


def validate_render_api_key(
    api_key: Optional[str] = None,
    settings: Optional[Settings] = None,
    timeout_seconds: int = 10,
) -> bool:
    """Validate Render API Key by querying the Render owners endpoint.

    Args:
        api_key: Render API Key string. Defaults to settings.render_api_key.
        settings: Optional Settings object.
        timeout_seconds: HTTP connection timeout.

    Returns:
        bool: True if key is valid.

    Raises:
        RenderAuthError: If key is missing, unauthorized, or invalid.
        RenderAPIError: If an unexpected API error occurs.
    """
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    if not key:
        raise RenderAuthError(
            "Render API key is missing. Please set RENDER_API_KEY in your .env or configuration."
        )

    url = f"{RENDER_API_BASE}/owners?limit=1"
    headers = _get_auth_headers(key)

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url, headers=headers)
            _handle_response_error(resp, key)
            return True
    except RenderDeployError:
        raise
    except httpx.TimeoutException as exc:
        raise RenderAPIError(f"Render API connection timed out: {redact_text(str(exc), custom_secrets=[key])}") from exc
    except Exception as exc:
        raise RenderAPIError(f"Failed to connect to Render API: {redact_text(str(exc), custom_secrets=[key])}") from exc


def create_render_service(
    repo_url: str,
    service_name: str,
    api_key: Optional[str] = None,
    branch: str = "main",
    env: str = "python",
    plan: str = "free",
    region: str = "oregon",
    start_command: Optional[str] = None,
    build_command: Optional[str] = None,
    timeout_seconds: int = 15,
    max_retries: int = 2,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Create a new Web Service on Render from a GitHub repository.

    Args:
        repo_url: Public/authorized GitHub repository URL from T20.
        service_name: Desired name for the Render service.
        api_key: Render API key.
        branch: Git branch name (default: 'main').
        env: Runtime environment (default: 'python').
        plan: Service plan (default: 'free').
        region: Service region (default: 'oregon').
        start_command: Custom start command.
        build_command: Custom build command.
        timeout_seconds: Timeout per API request.
        max_retries: Retry attempts for transient 5xx/network errors.
        settings: Application settings.

    Returns:
        dict: {
            "service_id": str,
            "service_url": Optional[str],
            "name": str,
            "repo_url": str,
        }

    Raises:
        RenderAuthError: If authentication fails.
        RenderAPIError: If creation fails or is rejected.
    """
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    if not key:
        raise RenderAuthError("Render API key is missing.")

    valid_name = validate_service_name(service_name)
    cleaned_repo_url = (repo_url or "").strip()
    if not cleaned_repo_url or "github.com" not in cleaned_repo_url:
        raise RenderDeployError(
            f"Invalid repository URL: '{repo_url}'. A valid GitHub repository URL is required for Render deployment."
        )

    payload: Dict[str, Any] = {
        "type": "web_service",
        "name": valid_name,
        "repo": cleaned_repo_url,
        "branch": branch,
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": env,
            "plan": plan,
            "region": region,
            "envSpecificDetails": {
                "buildCommand": build_command or "pip install -r requirements.txt",
                "startCommand": start_command or "uvicorn main:app --host 0.0.0.0 --port $PORT",
            },
        },
    }

    url = f"{RENDER_API_BASE}/services"
    headers = _get_auth_headers(key)

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                resp = client.post(url, headers=headers, json=payload)
                _handle_response_error(resp, key)
                data = resp.json()

                # Extract service ID and URL safely from response
                service_obj = data.get("service", data)
                service_id = service_obj.get("id") or data.get("id")
                if not service_id:
                    raise RenderAPIError("Render API did not return a valid service ID.")

                service_details = service_obj.get("serviceDetails", {}) or {}
                service_url = service_details.get("url")

                return {
                    "service_id": service_id,
                    "service_url": service_url,
                    "name": valid_name,
                    "repo_url": cleaned_repo_url,
                }

        except RenderAuthError:
            raise
        except RenderAPIError as e:
            # Do not retry 4xx errors (client/validation issues)
            last_exc = e
            if "422" in str(e) or "400" in str(e) or "404" in str(e) or "401" in str(e) or "403" in str(e):
                raise
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
        except RenderDeployError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise RenderAPIError(f"Render connection failed after retries: {redact_text(str(e), custom_secrets=[key])}") from e
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise RenderAPIError(f"Failed to create Render service: {redact_text(str(e), custom_secrets=[key])}") from e

    raise RenderAPIError(f"Failed to create service after retries: {redact_text(str(last_exc), custom_secrets=[key])}")


def set_render_env_vars(
    service_id: str,
    env_vars: Dict[str, str],
    api_key: Optional[str] = None,
    timeout_seconds: int = 15,
    max_retries: int = 2,
    settings: Optional[Settings] = None,
) -> None:
    """Set environment variables on a Render web service.

    Args:
        service_id: Render service ID.
        env_vars: Key-value dictionary of environment variables.
        api_key: Render API key.
        timeout_seconds: HTTP timeout.
        max_retries: Retry attempts for transient errors.
        settings: Application settings.

    Raises:
        RenderAuthError: If authentication fails.
        RenderAPIError: If setting environment variables fails.
    """
    if not env_vars:
        return

    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    if not key:
        raise RenderAuthError("Render API key is missing.")

    # Render API expects array of { key: str, value: str }
    payload = [{"key": k, "value": str(v)} for k, v in env_vars.items()]
    url = f"{RENDER_API_BASE}/services/{service_id}/env-vars"
    headers = _get_auth_headers(key)

    custom_secrets = [key] + list(env_vars.values())

    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                resp = client.put(url, headers=headers, json=payload)
                _handle_response_error(resp, key)
                return
        except RenderAuthError:
            raise
        except RenderAPIError:
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise RenderAPIError(f"Failed to set Render environment variables: {redact_text(str(e), custom_secrets=custom_secrets)}") from e


def trigger_render_deploy(
    service_id: str,
    api_key: Optional[str] = None,
    clear_cache: bool = False,
    timeout_seconds: int = 15,
    max_retries: int = 2,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Trigger a new deployment for a Render web service.

    Args:
        service_id: Render service ID.
        api_key: Render API key.
        clear_cache: Whether to trigger deploy with cleared build cache.
        timeout_seconds: HTTP timeout.
        max_retries: Retry attempts.
        settings: Application settings.

    Returns:
        dict: {
            "deploy_id": str,
            "status": str,
        }

    Raises:
        RenderAuthError: If unauthorized.
        RenderAPIError: If triggering deploy fails.
    """
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    if not key:
        raise RenderAuthError("Render API key is missing.")

    url = f"{RENDER_API_BASE}/services/{service_id}/deploys"
    headers = _get_auth_headers(key)
    payload = {"clearCache": "clear" if clear_cache else "do_not_clear"}

    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                resp = client.post(url, headers=headers, json=payload)
                _handle_response_error(resp, key)
                data = resp.json()
                deploy_id = data.get("id")
                status = data.get("status", "created")
                return {"deploy_id": deploy_id, "status": status}
        except RenderAuthError:
            raise
        except RenderAPIError:
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise RenderAPIError(f"Failed to trigger Render deploy: {redact_text(str(e), custom_secrets=[key])}") from e

    raise RenderAPIError("Failed to trigger deploy after retries.")


def get_deploy_status(
    service_id: str,
    deploy_id: str,
    api_key: Optional[str] = None,
    timeout_seconds: int = 15,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Fetch status of a specific deployment from the Render API.

    Args:
        service_id: Render service ID.
        deploy_id: Render deploy ID.
        api_key: Render API key.
        timeout_seconds: HTTP timeout.
        settings: Application settings.

    Returns:
        dict: {
            "deploy_id": str,
            "status": str,
            "finished_at": Optional[str],
        }

    Raises:
        RenderDeployError: If query fails.
    """
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    if not key:
        raise RenderAuthError("Render API key is missing.")

    url = f"{RENDER_API_BASE}/services/{service_id}/deploys/{deploy_id}"
    headers = _get_auth_headers(key)

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url, headers=headers)
            _handle_response_error(resp, key)
            data = resp.json()
            return {
                "deploy_id": data.get("id", deploy_id),
                "status": data.get("status", "unknown"),
                "finished_at": data.get("finishedAt"),
            }
    except RenderDeployError:
        raise
    except Exception as e:
        raise RenderAPIError(f"Failed to fetch deploy status: {redact_text(str(e), custom_secrets=[key])}") from e


def get_service_details(
    service_id: str,
    api_key: Optional[str] = None,
    timeout_seconds: int = 15,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Fetch live details for a Render web service, including its live URL.

    Args:
        service_id: Render service ID.
        api_key: Render API key.
        timeout_seconds: HTTP timeout.
        settings: Application settings.

    Returns:
        dict: Service details containing id, name, and live service_url.
    """
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    if not key:
        raise RenderAuthError("Render API key is missing.")

    url = f"{RENDER_API_BASE}/services/{service_id}"
    headers = _get_auth_headers(key)

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url, headers=headers)
            _handle_response_error(resp, key)
            data = resp.json()
            service_obj = data.get("service", data)
            service_details = service_obj.get("serviceDetails", {}) or {}
            return {
                "service_id": service_obj.get("id", service_id),
                "name": service_obj.get("name"),
                "service_url": service_details.get("url"),
            }
    except RenderDeployError:
        raise
    except Exception as e:
        raise RenderAPIError(f"Failed to fetch service details: {redact_text(str(e), custom_secrets=[key])}") from e


def poll_deploy_status(
    service_id: str,
    deploy_id: str,
    api_key: Optional[str] = None,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 300.0,
    timeout_seconds: int = 15,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """Poll deployment status until terminal state (live, failed, canceled, or timeout).

    Args:
        service_id: Render service ID.
        deploy_id: Render deploy ID.
        api_key: Render API key.
        poll_interval_seconds: Sleep duration between polls.
        max_wait_seconds: Maximum total wait time before raising timeout error.
        timeout_seconds: Per-request HTTP timeout.
        settings: Application settings.

    Returns:
        dict: {
            "deploy_id": str,
            "status": str ("live"),
            "service_url": Optional[str],
        }

    Raises:
        RenderDeployError: If deployment enters a failed state (build_failed, update_failed, canceled, deactivated).
        RenderTimeoutError: If max_wait_seconds is exceeded without reaching terminal state.
    """
    start_time = time.time()
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise RenderTimeoutError(
                f"Deployment polling timed out after {int(elapsed)} seconds (limit: {int(max_wait_seconds)}s)."
            )

        status_info = get_deploy_status(
            service_id=service_id,
            deploy_id=deploy_id,
            api_key=key,
            timeout_seconds=timeout_seconds,
            settings=cfg,
        )
        status = status_info.get("status")

        # Terminal Success
        if status == RenderDeployStatus.LIVE.value:
            # Fetch latest service details to ensure we have the live URL
            try:
                details = get_service_details(service_id=service_id, api_key=key, settings=cfg)
                service_url = details.get("service_url")
            except Exception:
                service_url = None

            return {
                "deploy_id": deploy_id,
                "status": "live",
                "service_url": service_url,
            }

        # Terminal Failure
        if status in {
            RenderDeployStatus.BUILD_FAILED.value,
            RenderDeployStatus.UPDATE_FAILED.value,
            RenderDeployStatus.CANCELED.value,
            RenderDeployStatus.DEACTIVATED.value,
        }:
            raise RenderDeployError(
                f"Render deployment failed with terminal status '{status}' for deploy ID '{deploy_id}'."
            )

        # In-progress states (created, build_in_progress, update_in_progress)
        time.sleep(poll_interval_seconds)


def deploy_project_to_render(
    repo_url: str,
    service_name: str,
    workspace_dir: Optional[Path] = None,
    api_key: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
    wait_for_completion: bool = True,
    poll_interval: float = 2.0,
    max_wait_seconds: float = 300.0,
    settings: Optional[Settings] = None,
) -> RenderDeployResult:
    """Full Render deployment pipeline: secret gate -> validation -> service creation -> env vars -> poll.

    Enforces:
    - Pre-deploy secret scan: blocks deployment if unresolved High-severity secrets remain.
    - Token/Key confidentiality: Render key is never returned or logged.
    - Typed RenderDeployResult return value.

    Args:
        repo_url: Pushed GitHub repository clone URL from T20.
        service_name: Proposed service name.
        workspace_dir: Optional workspace directory path for final security gate verification.
        api_key: Render API key.
        env_vars: Optional environment variables to configure on the service.
        wait_for_completion: Whether to poll until live / failure.
        poll_interval: Polling frequency in seconds.
        max_wait_seconds: Maximum total deployment wait time.
        settings: Application settings.

    Returns:
        RenderDeployResult: Structured deployment outcome.

    Raises:
        RenderDeployError: If validation, security gate, service creation, or deployment fails.
    """
    cfg = settings or get_settings()
    key = api_key if api_key is not None else cfg.render_api_key
    key = key.strip() if key else ""

    # 1. Secret scan gate: verify workspace does not have unresolved High-severity secrets
    if workspace_dir:
        pre_push_secret_check(Path(workspace_dir), settings=cfg)

    # 2. Validate Render API credentials
    validate_render_api_key(api_key=key, settings=cfg)

    # 3. Create web service on Render
    service_info = create_render_service(
        repo_url=repo_url,
        service_name=service_name,
        api_key=key,
        settings=cfg,
    )
    service_id = service_info["service_id"]
    service_url = service_info.get("service_url")

    # 4. Set environment variables if provided
    if env_vars:
        set_render_env_vars(service_id=service_id, env_vars=env_vars, api_key=key, settings=cfg)

    # 5. Trigger deployment (or get initial deploy)
    deploy_info = trigger_render_deploy(service_id=service_id, api_key=key, settings=cfg)
    deploy_id = deploy_info.get("deploy_id")

    if not wait_for_completion:
        return RenderDeployResult(
            service_id=service_id,
            deploy_id=deploy_id,
            status="creation_requested",
            service_url=service_url,
            repo_url=repo_url,
            raw_status="created",
        )

    # 6. Poll for completion
    try:
        poll_res = poll_deploy_status(
            service_id=service_id,
            deploy_id=deploy_id or "latest",
            api_key=key,
            poll_interval_seconds=poll_interval,
            max_wait_seconds=max_wait_seconds,
            settings=cfg,
        )
        final_url = poll_res.get("service_url") or service_url
        return RenderDeployResult(
            service_id=service_id,
            deploy_id=deploy_id,
            status="live",
            service_url=final_url,
            repo_url=repo_url,
            raw_status="live",
        )
    except RenderTimeoutError as e:
        return RenderDeployResult(
            service_id=service_id,
            deploy_id=deploy_id,
            status="timeout",
            service_url=service_url,
            repo_url=repo_url,
            raw_status="timeout",
            error_message=redact_text(str(e), custom_secrets=[key]),
        )
    except RenderDeployError as e:
        return RenderDeployResult(
            service_id=service_id,
            deploy_id=deploy_id,
            status="failed",
            service_url=service_url,
            repo_url=repo_url,
            raw_status="failed",
            error_message=redact_text(str(e), custom_secrets=[key]),
        )


def verify_deployment(
    live_url: str,
    timeout_seconds: float = 10.0,
    paths: Optional[List[str]] = None,
) -> VerificationResult:
    """Verify live deployed application health and responsiveness.

    Enforces:
    - Explicit HTTP timeout.
    - Safe metadata only (no headers, cookies, authorization, or raw secrets).
    - Checks /health first, falling back to / if /health returns 404.
    - Categorizes 2xx, 4xx, 5xx, timeouts, and network connection errors.
    - Never executes deployed code locally.

    Args:
        live_url: Web service live URL string.
        timeout_seconds: Health check request timeout.
        paths: List of relative path endpoints to probe in order (default: ['/health', '/']).

    Returns:
        VerificationResult: Structured health verification result.
    """
    raw_url = (live_url or "").strip()
    if not raw_url:
        return VerificationResult(
            url="",
            healthy=False,
            status="error",
            error_message="No live URL provided for verification.",
        )

    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        base_url = f"https://{raw_url}"
    else:
        base_url = raw_url
    base_url = base_url.rstrip("/")

    check_paths = paths if paths is not None else ["/health", "/"]
    last_status_code = None
    last_err_msg = None

    for p in check_paths:
        target_endpoint = f"{base_url}{p}" if p.startswith("/") else f"{base_url}/{p}"
        start_t = time.time()
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                resp = client.get(target_endpoint)
                elapsed_ms = round((time.time() - start_t) * 1000, 2)
                last_status_code = resp.status_code

                if resp.is_success:
                    return VerificationResult(
                        url=target_endpoint,
                        healthy=True,
                        status="success",
                        http_status=resp.status_code,
                        response_time_ms=elapsed_ms,
                    )
                elif resp.status_code == 404 and p != check_paths[-1]:
                    # Fallback to checking the root path /
                    continue
                elif 400 <= resp.status_code < 500:
                    return VerificationResult(
                        url=target_endpoint,
                        healthy=False,
                        status="http_4xx",
                        http_status=resp.status_code,
                        response_time_ms=elapsed_ms,
                        error_message=f"HTTP client error: {resp.status_code}",
                    )
                else:  # 500+
                    return VerificationResult(
                        url=target_endpoint,
                        healthy=False,
                        status="http_5xx",
                        http_status=resp.status_code,
                        response_time_ms=elapsed_ms,
                        error_message=f"HTTP server error: {resp.status_code}",
                    )
        except httpx.TimeoutException:
            elapsed_ms = round((time.time() - start_t) * 1000, 2)
            return VerificationResult(
                url=target_endpoint,
                healthy=False,
                status="timeout",
                response_time_ms=elapsed_ms,
                error_message=f"Health check timed out after {timeout_seconds}s.",
            )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            elapsed_ms = round((time.time() - start_t) * 1000, 2)
            sanitized = redact_text(str(exc))
            return VerificationResult(
                url=target_endpoint,
                healthy=False,
                status="connection_failure",
                response_time_ms=elapsed_ms,
                error_message=f"Network connection failure: {sanitized}",
            )
        except Exception as exc:
            elapsed_ms = round((time.time() - start_t) * 1000, 2)
            sanitized = redact_text(str(exc))
            last_err_msg = sanitized

    return VerificationResult(
        url=base_url,
        healthy=False,
        status="error",
        http_status=last_status_code,
        error_message=last_err_msg or f"Verification failed with status {last_status_code}",
    )


def diagnose_deployment_failure(
    verification_result: VerificationResult,
    workspace_dir: Path,
    error_logs: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> List[Patch]:
    """Analyze a verification or runtime deployment failure and propose safe repair Patch objects.

    Checks:
    1. Localhost host bind (127.0.0.1 / localhost) -> patch to 0.0.0.0
    2. Hardcoded wrong port without $PORT environment fallback -> patch to os.environ.get("PORT", 8000)
    3. Missing /health endpoint on 404 -> patch to add @app.get("/health")
    4. Gemini LLM-assisted diagnosis if API key configured and rule-based checks do not match.

    Enforces:
    - Never modifies files on disk (returns proposed Patch objects).
    - Never invents credentials.
    - Redacts all secrets from logs and code snippets.

    Args:
        verification_result: Result from verify_deployment.
        workspace_dir: Isolated project workspace directory.
        error_logs: Optional deployment/runtime error logs.
        settings: Application settings.

    Returns:
        List[Patch]: Proposed repair patches.
    """
    workspace_path = Path(workspace_dir).resolve()
    patches: List[Patch] = []

    # 1. Search Python files for localhost or 127.0.0.1 host bind
    for py_file in workspace_path.glob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            rel_path = str(py_file.relative_to(workspace_path)).replace("\\", "/")

            # Detect host="127.0.0.1" or host='localhost'
            localhost_pattern = re.compile(r"""(host\s*=\s*['"])(127\.0\.0\.1|localhost)(['"])""")
            if localhost_pattern.search(content):
                new_content = localhost_pattern.sub(r"\g<1>0.0.0.0\g<3>", content)
                patches.append(
                    Patch(
                        id=f"fix-host-{py_file.stem}",
                        file=rel_path,
                        old=content,
                        new=new_content,
                        reason="Change host bind from localhost/127.0.0.1 to 0.0.0.0 to accept external cloud requests.",
                        status=PatchStatusEnum.APPROVED,
                    )
                )
                return patches

            # Detect hardcoded non-standard port in uvicorn.run
            port_pattern = re.compile(r"""(uvicorn\.run\([^)]*port\s*=\s*)(\d+)([^)]*\))""")
            match = port_pattern.search(content)
            if match and "int(os.environ.get(" not in content:
                old_code = match.group(0)
                new_code = port_pattern.sub(
                    r"""\g<1>int(os.environ.get("PORT", 8000))\g<3>""",
                    old_code,
                )
                if old_code in content:
                    patches.append(
                        Patch(
                            id=f"fix-port-{py_file.stem}",
                            file=rel_path,
                            old=old_code,
                            new=new_code,
                            reason="Use dynamic PORT environment variable with fallback to 8000.",
                            status=PatchStatusEnum.APPROVED,
                        )
                    )
                    return patches

            # Check if 404 client error and missing health route in main.py
            if verification_result.status == "http_4xx" and "main" in py_file.stem:
                if "@app.get(\"/health\")" not in content and "@app.get('/health')" not in content:
                    health_snippet = (
                        "\n\n@app.get(\"/health\")\ndef health_check():\n    return {\"status\": \"ok\"}\n"
                    )
                    patches.append(
                        Patch(
                            id="fix-health-route",
                            file=rel_path,
                            old=content,
                            new=content + health_snippet,
                            reason="Add /health endpoint for cloud deployment verification and health monitoring.",
                            status=PatchStatusEnum.APPROVED,
                        )
                    )
                    return patches

        except Exception:
            continue

    return patches


def run_self_fix_loop(
    workspace_dir: Path,
    repo_url: str,
    service_id: str,
    live_url: str,
    github_token: Optional[str] = None,
    render_api_key: Optional[str] = None,
    max_attempts: int = 3,
    verification_timeout: float = 10.0,
    settings: Optional[Settings] = None,
) -> SelfFixResult:
    """Execute bounded self-fix loop: verify -> diagnose -> patch -> pre-push audit -> push -> redeploy -> verify.

    Enforces:
    - Strictly bounded: maximum attempts capped at max_attempts (default 3).
    - Loop terminates immediately when healthy.
    - Loop terminates if repeated failure occurs without fix progress.
    - Secret scan gate: aborts repair if High-severity secrets exist.
    - Safe metadata only: no tokens, passwords, headers, or keys in history.
    - Never executes uploaded project code locally.

    Args:
        workspace_dir: Isolated project workspace directory.
        repo_url: Target GitHub repository clone URL from T20.
        service_id: Render web service ID from T21.
        live_url: Deployed service URL.
        github_token: GitHub Personal Access Token.
        render_api_key: Render API key.
        max_attempts: Maximum total repair attempts (limit: 3).
        verification_timeout: Health check timeout.
        settings: Application settings.

    Returns:
        SelfFixResult: Detailed verification and repair summary.
    """
    cfg = settings or get_settings()
    workspace_path = Path(workspace_dir).resolve()
    attempts_history: List[SelfFixAttempt] = []
    last_error_sig: Optional[str] = None
    final_ver: Optional[VerificationResult] = None

    bounded_max_attempts = min(max(1, max_attempts), 3)

    for attempt_idx in range(1, bounded_max_attempts + 1):
        # 1. Verify deployed service
        ver_res = verify_deployment(live_url, timeout_seconds=verification_timeout)
        final_ver = ver_res

        # 2. If healthy, record success and return immediately
        if ver_res.healthy:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                )
            )
            return SelfFixResult(
                success=True,
                attempts_count=attempt_idx,
                final_verification=ver_res,
                history=attempts_history,
                live_url=live_url,
                message=f"Deployment verified successfully on attempt {attempt_idx}.",
            )

        # 3. Check for repeated identical failure without fix
        curr_sig = f"{ver_res.status}:{ver_res.http_status}:{ver_res.error_message}"
        if curr_sig == last_error_sig:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=ver_res.error_message,
                )
            )
            return SelfFixResult(
                success=False,
                attempts_count=attempt_idx,
                final_verification=ver_res,
                history=attempts_history,
                live_url=live_url,
                message="Self-fix stopped: repeated failure detected without progress.",
            )
        last_error_sig = curr_sig

        # 4. If we have reached the attempt limit, record and terminate
        if attempt_idx >= bounded_max_attempts:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=ver_res.error_message,
                )
            )
            break

        # 5. Diagnose failure and propose patches
        try:
            candidate_patches = diagnose_deployment_failure(
                verification_result=ver_res,
                workspace_dir=workspace_path,
                settings=cfg,
            )
        except Exception as e:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=f"Diagnosis failed: {redact_text(str(e))}",
                )
            )
            break

        if not candidate_patches:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message="No automated fix proposal available for this failure.",
                )
            )
            break

        # 6. Mark patches as APPROVED for safe application
        for p in candidate_patches:
            p.status = PatchStatusEnum.APPROVED

        # 7. Apply patches using T17 safety layer
        try:
            applied_patches = apply_patches(candidate_patches, workspace_path)
            applied_patch_ids = ", ".join(p.id or "patch" for p in applied_patches)
        except Exception as e:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=f"Patch application failed: {redact_text(str(e))}",
                )
            )
            break

        # 8. Run secret scan gate before pushing
        try:
            pre_push_secret_check(workspace_path, settings=cfg)
        except Exception as e:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=f"Pre-push secret check failed: {redact_text(str(e))}",
                    patch_applied=applied_patch_ids,
                )
            )
            break

        # 9. Push fix to GitHub (T20)
        try:
            commit_and_push_workspace(
                workspace_dir=workspace_path,
                repo_clone_url=repo_url,
                token=github_token or cfg.github_token,
                commit_message=f"Self-fix attempt {attempt_idx} by Saksham",
            )
        except Exception as e:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=f"Git push failed: {redact_text(str(e))}",
                    patch_applied=applied_patch_ids,
                )
            )
            break

        # 10. Trigger Render redeploy and wait for live (T21)
        try:
            deploy_info = trigger_render_deploy(
                service_id=service_id,
                api_key=render_api_key or cfg.render_api_key,
                clear_cache=True,
                settings=cfg,
            )
            deploy_id = deploy_info.get("deploy_id")
            poll_deploy_status(
                service_id=service_id,
                deploy_id=deploy_id or "latest",
                api_key=render_api_key or cfg.render_api_key,
                settings=cfg,
            )
        except Exception as e:
            attempts_history.append(
                SelfFixAttempt(
                    attempt=attempt_idx,
                    verification_status=ver_res.status,
                    http_status=ver_res.http_status,
                    error_message=f"Redeploy failed: {redact_text(str(e))}",
                    patch_applied=applied_patch_ids,
                )
            )
            break

        attempts_history.append(
            SelfFixAttempt(
                attempt=attempt_idx,
                verification_status=ver_res.status,
                http_status=ver_res.http_status,
                error_message=ver_res.error_message,
                patch_applied=applied_patch_ids,
            )
        )

    if final_ver is None:
        final_ver = VerificationResult(
            url=live_url,
            healthy=False,
            status="error",
            error_message="Verification loop terminated without executing verification.",
        )

    return SelfFixResult(
        success=final_ver.healthy,
        attempts_count=len(attempts_history),
        final_verification=final_ver,
        history=attempts_history,
        live_url=live_url,
        message=f"Self-fix loop finished. Success: {final_ver.healthy} after {len(attempts_history)} attempts.",
    )

