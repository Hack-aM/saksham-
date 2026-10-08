import asyncio
import io
import os
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from audit import AuditError, GitleaksNotFoundError, audit_project
from config import Settings, get_settings
from db import get_analysis, init_db, list_analyses, list_deployments, save_analysis, save_deployment
from deployer import deploy_project_to_render, run_self_fix_loop
from github_push import push_workspace_to_github
from fixer import (
    FixerError,
    apply_patches,
    propose_missing_file_patches,
    propose_patches_for_issues,
)
from redact import redact_text
from scanner import scan_project
from schemas import (
    AnalysisResult,
    ApproveRequest,
    ApproveResponse,
    Issue,
    Patch,
    PatchStatusEnum,
    ProgressEvent,
    ScanResult,
    SeverityEnum,
    StageEnum,
)
from upload import (
    ExtractedProject,
    InvalidUploadError,
    UploadError,
    UploadSecurityError,
    UploadSizeError,
    extract_project_to_workspace,
    extract_project_zip,
)

BASE_DIR = Path(__file__).resolve().parent
RUNS_BASE_DIR = BASE_DIR / "tmp" / "runs"
MAX_EVENT_HISTORY_PER_RUN = 100


@dataclass
class ActiveRun:
    """In-memory active workspace run state maintained between /analyze and /approve."""
    run_id: str
    project_name: str
    workspace_dir: Path
    created_at: float
    scan_result: ScanResult
    issues: List[Issue]
    score: int
    reasons: List[str]
    history_status: str
    patches: List[Patch] = field(default_factory=list)


# Active in-memory runs registry keyed by run_id (ARCHITECTURE.md section 7.1)
RUNS: Dict[str, ActiveRun] = {}

# Bounded in-memory event history and live subscriber queues per run_id (T23)
RUN_EVENTS: Dict[str, List[ProgressEvent]] = {}
RUN_EVENT_SUBSCRIBERS: Dict[str, List[asyncio.Queue]] = {}


def publish_progress_event(
    run_id: str,
    stage: str,
    status: str,
    message: str,
    percentage: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> ProgressEvent:
    """Publish a structured, redacted progress event to memory history and active SSE subscribers.

    Enforces:
    - Never exposes API keys, passwords, tokens, or raw secrets (runs redact_text on all text).
    - Bounded in-memory history per run (max 100 events).
    - Thread-safe / asyncio broadcast to all active SSE queues for this run.

    Args:
        run_id: Associated run ID.
        stage: Pipeline stage (e.g. 'upload', 'scan', 'audit', 'fix', 'approve', 'complete').
        status: Stage status (e.g. 'started', 'in_progress', 'completed', 'blocked', 'failed').
        message: User-friendly descriptive message.
        percentage: Optional progress percentage (0-100).
        details: Optional safe dictionary metadata.

    Returns:
        ProgressEvent: Created and dispatched event.
    """
    sanitized_msg = redact_text(message)
    sanitized_details = None
    if details:
        sanitized_details = {}
        for k, v in details.items():
            if isinstance(v, str):
                sanitized_details[k] = redact_text(v)
            else:
                sanitized_details[k] = v

    event = ProgressEvent(
        run_id=run_id,
        stage=stage,
        status=status,
        message=sanitized_msg,
        percentage=percentage,
        details=sanitized_details,
        timestamp=time.time(),
    )

    # 1. Store in bounded event history
    history = RUN_EVENTS.setdefault(run_id, [])
    history.append(event)
    if len(history) > MAX_EVENT_HISTORY_PER_RUN:
        history.pop(0)

    # 2. Dispatch to all active async subscribers for this run
    subscribers = RUN_EVENT_SUBSCRIBERS.get(run_id, [])
    for q in list(subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass

    return event


def cleanup_all_workspaces_on_startup(base_dir: Optional[Path] = None) -> None:
    """Clean up leftover directories in tmp/runs from prior terminated runs on startup."""
    RUN_EVENTS.clear()
    RUN_EVENT_SUBSCRIBERS.clear()
    target_base = base_dir or RUNS_BASE_DIR
    if target_base.exists() and target_base.is_dir():
        for item in target_base.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)


def cleanup_expired_workspaces(ttl_seconds: Optional[int] = None) -> None:
    """Purge expired workspaces from memory and disk based on workspace TTL."""
    cfg = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else cfg.workspace_ttl_seconds
    now = time.time()
    expired_ids = [
        run_id for run_id, run in RUNS.items()
        if now - run.created_at > ttl
    ]
    for run_id in expired_ids:
        run = RUNS.pop(run_id, None)
        RUN_EVENTS.pop(run_id, None)
        RUN_EVENT_SUBSCRIBERS.pop(run_id, None)
        if run and run.workspace_dir.exists():
            shutil.rmtree(run.workspace_dir, ignore_errors=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: initialize database and cleanup stale workspaces on startup."""
    init_db()
    cleanup_all_workspaces_on_startup()
    yield


app = FastAPI(
    title="Saksham API",
    description="AI Pre-Push Security & Deployment Safety Agent",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local React/Vite development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(UploadSizeError)
async def upload_size_error_handler(request: Request, exc: UploadSizeError):
    """Translate upload size limit violations into HTTP 413 Request Entity Too Large responses."""
    return JSONResponse(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        content={"error": str(exc), "detail": str(exc)},
    )


@app.exception_handler(UploadError)
async def upload_error_handler(request: Request, exc: UploadError):
    """Translate upload domain exceptions into clean HTTP 400 responses."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": str(exc), "detail": str(exc)},
    )


@app.exception_handler(FixerError)
async def fixer_error_handler(request: Request, exc: FixerError):
    """Translate patch/fix domain errors into clean HTTP 400 responses."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": str(exc)},
    )


@app.exception_handler(GitleaksNotFoundError)
async def gitleaks_not_found_error_handler(request: Request, exc: GitleaksNotFoundError):
    """Translate missing gitleaks binary into clean HTTP 503 response."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": str(exc)},
    )


@app.exception_handler(AuditError)
async def audit_error_handler(request: Request, exc: AuditError):
    """Translate audit scanning failures into clean HTTP 500 responses."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": str(exc)},
    )


@app.get("/health")
def health_check():
    """Health check for Saksham API itself."""
    return {"status": "ok", "service": "Saksham API"}


@app.post("/upload")
async def upload_project_zip(file: UploadFile = File(...)):
    """Upload and validate a project ZIP archive.

    Streams the uploaded body in chunks, enforcing the compressed limit immediately
    without unconstrained in-memory buffering.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise InvalidUploadError("File must have a .zip extension.")

    cfg = get_settings()
    chunk_size = 64 * 1024  # 64 KB streaming buffer
    total_received = 0
    buffer = io.BytesIO()

    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_received += len(chunk)
        if total_received > cfg.max_upload_size_bytes:
            raise UploadSizeError(
                f"Uploaded file size exceeds the maximum limit of {cfg.max_upload_size_bytes} bytes (25 MB)."
            )
        buffer.write(chunk)

    buffer.seek(0)

    with extract_project_zip(buffer) as extracted:
        return {
            "status": "valid",
            "filename": file.filename,
            "file_count": extracted.file_count,
            "history_available": extracted.history_available,
            "total_size_bytes": extracted.total_size_bytes,
        }


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_project(file: UploadFile = File(...)) -> AnalysisResult:
    """Analyze an uploaded project ZIP archive.

    Safely streams and extracts the archive into an isolated run workspace (tmp/runs/{run_id}),
    runs rule-based stack detection, secret scans on files and git history,
    configuration checks, computes the deploy readiness score, and proposes safe patches.
    Returns AnalysisResult and maintains workspace in memory for patch review.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise InvalidUploadError("File must have a .zip extension.")

    cfg = get_settings()
    cleanup_expired_workspaces()

    chunk_size = 64 * 1024  # 64 KB streaming buffer
    total_received = 0
    buffer = io.BytesIO()

    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_received += len(chunk)
        if total_received > cfg.max_upload_size_bytes:
            raise UploadSizeError(
                f"Uploaded file size exceeds the maximum limit of {cfg.max_upload_size_bytes} bytes (25 MB)."
            )
        buffer.write(chunk)

    buffer.seek(0)

    run_id = secrets.token_urlsafe(16)
    project_name = Path(file.filename).stem or "project"
    workspace_dir = RUNS_BASE_DIR / run_id

    # Safely extract archive to isolated workspace directory
    extracted = extract_project_to_workspace(buffer, workspace_dir, settings=cfg)
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.UPLOAD.value,
        status="completed",
        message=f"Extracted {extracted.file_count} files from archive.",
        percentage=15,
    )

    # 1. Stack and framework detection (T09)
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.SCAN.value,
        status="started",
        message="Detecting project language, framework, and entry point...",
        percentage=25,
    )
    scan_res = scan_project(extracted.path, settings=cfg)
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.SCAN.value,
        status="completed",
        message=f"Detected stack: {scan_res.stack}",
        percentage=40,
    )

    # 2. Comprehensive security & config audit with readiness score (T10, T11, T12, T13)
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.AUDIT.value,
        status="started",
        message="Running secret scan and configuration checks...",
        percentage=50,
    )
    issues, score, reasons, history_status = audit_project(
        extracted.path,
        history_available=extracted.history_available,
        settings=cfg,
    )
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.AUDIT.value,
        status="completed",
        message=f"Audit completed with Deploy Readiness Score {score}/100.",
        percentage=70,
    )

    # 3. Generate proposed fixes and missing starter template patches (T16, T18)
    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.FIX.value,
        status="started",
        message="Proposing automated fixes and starter templates...",
        percentage=80,
    )
    patches: List[Patch] = []
    issue_patches = propose_patches_for_issues(issues, extracted.path)
    patches.extend(issue_patches)

    # Propose missing standard files (.gitignore, .env.example, Dockerfile, ci.yml, README)
    template_patches = propose_missing_file_patches(
        extracted.path,
        project_name=project_name,
        entry_point=scan_res.entry_point or "main",
    )
    patches.extend(template_patches)

    # Store active run in memory
    RUNS[run_id] = ActiveRun(
        run_id=run_id,
        project_name=project_name,
        workspace_dir=extracted.path,
        created_at=time.time(),
        scan_result=scan_res,
        issues=issues,
        score=score,
        reasons=reasons,
        history_status=history_status,
        patches=patches,
    )

    # Persist analysis in SQLite database (with zero raw secrets stored)
    db_issues = [issue.model_dump() for issue in issues]
    db_patches = [patch.model_dump() for patch in patches]
    analysis_db_id = save_analysis(
        project_name=project_name,
        stack=scan_res.stack,
        score=score,
        issues=db_issues,
        patches=db_patches,
        analysis_id=run_id,
        db_path=cfg.db_path,
    )

    publish_progress_event(
        run_id=run_id,
        stage=StageEnum.COMPLETE.value,
        status="completed",
        message=f"Analysis complete. Score {score}/100 with {len(issues)} issue(s) and {len(patches)} fix(es).",
        percentage=100,
    )

    return AnalysisResult(
        id=analysis_db_id,
        run_id=run_id,
        project_name=project_name,
        stack=scan_res.stack,
        score=score,
        reasons=reasons,
        issues=issues,
        patches=patches,
        history_status=history_status,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def run_deployment_pipeline_sync(
    run_id: str,
    repo_name: Optional[str] = None,
    visibility: str = "public",
    settings: Optional[Settings] = None,
) -> None:
    """Execute complete post-approval deployment pipeline in background.

    Steps:
    1. GitHub: Token validation -> pre-push secret check -> repo creation -> git commit/push
    2. Deploy: Create/trigger Render web service deployment -> poll to live
    3. Verify: Post-deploy health checks & bounded self-fix loop
    4. Persist: Save deployment record to SQLite db
    5. SSE: Stream all progress events and emit terminal COMPLETE or ERROR event.
    """
    import re
    cfg = settings or get_settings()
    run = RUNS.get(run_id)
    if not run or not run.workspace_dir.exists():
        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.ERROR.value,
            status="failed",
            message="Workspace expired or run not found. Cannot proceed with deployment.",
        )
        return

    effective_repo_name = repo_name or run.project_name or "fastapi-app"
    effective_repo_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", effective_repo_name).lower().strip("-")
    if not effective_repo_name:
        effective_repo_name = "fastapi-app"

    try:
        # Step 1: GitHub Push
        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.GITHUB.value,
            status="started",
            message=f"Creating GitHub repository '{effective_repo_name}' and committing workspace...",
            percentage=60,
        )

        push_result = push_workspace_to_github(
            workspace_dir=run.workspace_dir,
            repo_name=effective_repo_name,
            private=(visibility == "private"),
            settings=cfg,
        )

        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.GITHUB.value,
            status="completed",
            message=f"Pushed workspace to GitHub: {push_result['repo_url']}",
            percentage=70,
            details={
                "repo_url": push_result["repo_url"],
                "clone_url": push_result["clone_url"],
                "commit_sha": push_result["commit_sha"],
            },
        )

        # Step 2: Render Deployment
        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.DEPLOY.value,
            status="started",
            message="Creating and triggering Render web service deployment...",
            percentage=75,
        )

        deploy_res = deploy_project_to_render(
            repo_url=push_result["repo_url"],
            service_name=effective_repo_name,
            workspace_dir=run.workspace_dir,
            settings=cfg,
        )

        live_url = deploy_res.live_url or deploy_res.service_url or f"https://{effective_repo_name}.onrender.com"

        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.DEPLOY.value,
            status="completed",
            message=f"Render deployment is live at {live_url}",
            percentage=85,
            details={
                "live_url": live_url,
                "service_id": deploy_res.service_id,
                "deploy_id": deploy_res.deploy_id,
            },
        )

        # Step 3: Verification & Bounded Self-Fix
        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.VERIFY.value,
            status="started",
            message=f"Performing live health check verification on {live_url}...",
            percentage=90,
        )

        self_fix_res = run_self_fix_loop(
            live_url=live_url,
            workspace_dir=run.workspace_dir,
            repo_clone_url=push_result.get("clone_url"),
            service_id=deploy_res.service_id,
            settings=cfg,
        )

        if self_fix_res.success:
            publish_progress_event(
                run_id=run_id,
                stage=StageEnum.VERIFY.value,
                status="completed",
                message=f"Health check verified successfully (HTTP {self_fix_res.final_verification.http_status or 200}).",
                percentage=95,
                details={
                    "live_url": live_url,
                    "http_status": self_fix_res.final_verification.http_status,
                },
            )

            # Step 4: Persist Deployment to SQLite DB
            save_deployment(
                analysis_id=run_id,
                repo_url=push_result["repo_url"],
                live_url=live_url,
                platform="Render",
                health_status=f"{self_fix_res.final_verification.http_status or 200} OK",
                final_score=run.score,
                logs=f"Verified live at {live_url}. Attempts: {self_fix_res.attempts_count}",
                db_path=cfg.db_path,
            )

            # Step 5: Terminal COMPLETE Event
            publish_progress_event(
                run_id=run_id,
                stage=StageEnum.COMPLETE.value,
                status="completed",
                message=f"Project deployed and verified successfully! Live at {live_url}",
                percentage=100,
                details={
                    "live_url": live_url,
                    "repo_url": push_result["repo_url"],
                    "final_score": run.score,
                },
            )
        else:
            err_detail = self_fix_res.message or "Deployment health verification failed."
            publish_progress_event(
                run_id=run_id,
                stage=StageEnum.ERROR.value,
                status="failed",
                message=f"Health verification failed: {err_detail}",
                details={
                    "live_url": live_url,
                    "repo_url": push_result.get("repo_url"),
                    "attempts": self_fix_res.attempts_count,
                },
            )
            # Record failed deployment in DB
            save_deployment(
                analysis_id=run_id,
                repo_url=push_result["repo_url"],
                live_url=live_url,
                platform="Render",
                health_status=f"Failed ({self_fix_res.final_verification.status})",
                final_score=run.score,
                logs=f"Verification failed: {self_fix_res.message}",
                db_path=cfg.db_path,
            )

    except Exception as e:
        sanitized_msg = redact_text(str(e))
        publish_progress_event(
            run_id=run_id,
            stage=StageEnum.ERROR.value,
            status="failed",
            message=f"Deployment pipeline error: {sanitized_msg}",
        )


@app.post("/approve", response_model=ApproveResponse)
async def approve_and_apply_patches(
    request: ApproveRequest,
    background_tasks: BackgroundTasks,
) -> ApproveResponse:
    """Explicit human-in-the-loop approval gate for proposed patches.

    Validates the workspace run_id, applies only user-approved patches in memory
    and to the isolated workspace, executes the mandatory secret re-scan gate,
    and returns updated score and remaining issues.
    """
    run = RUNS.get(request.run_id)
    if not run or not run.workspace_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' not found or workspace expired. Please re-run analysis.",
        )

    cfg = get_settings()
    approved_ids = set(request.approved_patch_ids)
    patches_to_apply: List[Patch] = []

    publish_progress_event(
        run_id=request.run_id,
        stage=StageEnum.APPROVE.value,
        status="started",
        message=f"Applying {len(approved_ids)} approved patch(es)...",
        percentage=20,
    )

    for patch in run.patches:
        if patch.id in approved_ids:
            patch.status = PatchStatusEnum.APPROVED
            patches_to_apply.append(patch)
        else:
            patch.status = PatchStatusEnum.REJECTED

    # 1. Apply approved patches to the isolated workspace
    if patches_to_apply:
        apply_patches(patches_to_apply, run.workspace_dir)

    publish_progress_event(
        run_id=request.run_id,
        stage=StageEnum.APPROVE.value,
        status="in_progress",
        message=f"Applied {len(patches_to_apply)} patch(es). Running secret re-scan gate...",
        percentage=40,
    )

    # 2. Secret Re-Scan Gate (Mandatory safety verification before push)
    remaining_issues, new_score, new_reasons, _ = audit_project(
        run.workspace_dir,
        history_available=False,
        settings=cfg,
    )

    # Update in-memory run state with post-patch audit findings
    run.score = new_score
    run.issues = remaining_issues
    run.reasons = new_reasons

    # Check for unresolved High-severity secret leaks in workspace
    has_unresolved_secrets = any(
        issue.severity == SeverityEnum.HIGH for issue in remaining_issues
    )

    if has_unresolved_secrets:
        publish_progress_event(
            run_id=request.run_id,
            stage=StageEnum.ERROR.value,
            status="blocked",
            message="Push blocked: unresolved High-severity secret leaks remain in the workspace.",
            percentage=40,
        )
        return ApproveResponse(
            status="blocked",
            run_id=request.run_id,
            applied_patches_count=len(patches_to_apply),
            score=new_score,
            remaining_issues=remaining_issues,
            message="Push blocked: unresolved High-severity secret leaks remain in the workspace. Secrets must be fixed before deployment.",
        )

    publish_progress_event(
        run_id=request.run_id,
        stage=StageEnum.APPROVE.value,
        status="completed",
        message=f"Secret gate passed with score {new_score}/100. Workspace ready for GitHub push and deployment.",
        percentage=50,
    )

    # Schedule complete deployment pipeline in background
    background_tasks.add_task(
        run_deployment_pipeline_sync,
        request.run_id,
        request.repo_name or run.project_name,
        request.visibility,
        cfg,
    )

    return ApproveResponse(
        status="applied",
        run_id=request.run_id,
        applied_patches_count=len(patches_to_apply),
        score=new_score,
        remaining_issues=remaining_issues,
        message=f"Successfully applied {len(patches_to_apply)} approved patch(es). Secret gate passed with readiness score {new_score}/100.",
    )


@app.get("/events/{run_id}")
async def stream_run_events(run_id: str, request: Request):
    """Stream real-time progress events for a run using Server-Sent Events (SSE).

    Enforces:
    - Returns text/event-stream with data: <JSON>\n\n format.
    - Yields all past events for the run upon connection (no missed events).
    - Streams live broadcast events via per-subscriber asyncio queue.
    - Safe disconnect handling without crashing the pipeline.
    - Zero plain text secrets, API keys, or raw tokens.
    """
    if run_id not in RUNS and run_id not in RUN_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found.",
        )

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        subscribers = RUN_EVENT_SUBSCRIBERS.setdefault(run_id, [])
        subscribers.append(queue)

        try:
            # 1. Send all past recorded events first
            history = list(RUN_EVENTS.get(run_id, []))
            for event in history:
                yield f"data: {event.model_dump_json()}\n\n"

            # If the latest event is terminal (e.g. complete or error), finish stream cleanly
            if history and history[-1].stage in {StageEnum.COMPLETE.value, StageEnum.ERROR.value}:
                return

            # 2. Stream live events as they occur
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event: ProgressEvent = await asyncio.wait_for(queue.get(), timeout=10.0)
                    yield f"data: {event.model_dump_json()}\n\n"
                    if event.stage in {StageEnum.COMPLETE.value, StageEnum.ERROR.value}:
                        break
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"

        finally:
            if run_id in RUN_EVENT_SUBSCRIBERS:
                try:
                    RUN_EVENT_SUBSCRIBERS[run_id].remove(queue)
                    if not RUN_EVENT_SUBSCRIBERS[run_id]:
                        del RUN_EVENT_SUBSCRIBERS[run_id]
                except (ValueError, KeyError):
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/history")
async def get_history(limit: int = 50):
    """Retrieve list of recent analyses and deployment records from database."""
    deployments = list_deployments(limit=limit)
    analyses = list_analyses(limit=limit)
    return {
        "analyses": analyses,
        "deployments": deployments,
    }


@app.get("/history/{analysis_id}")
async def get_history_analysis(analysis_id: str):
    """Retrieve details of a specific past analysis run."""
    analysis = get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis '{analysis_id}' not found.",
        )
    return analysis


@app.get("/connections")
async def get_connections():
    """Retrieve integration connection statuses using safe metadata only (no secrets/tokens returned)."""
    cfg = get_settings()
    return {
        "gemini": {
            "name": "Google Gemini",
            "configured": bool(cfg.gemini_api_key),
            "model": cfg.gemini_model,
            "status": "configured" if cfg.gemini_api_key else "not_configured",
            "description": "Used for LLM-assisted patch diagnosis and proposals.",
        },
        "github": {
            "name": "GitHub",
            "configured": bool(cfg.github_token),
            "status": "configured" if cfg.github_token else "not_configured",
            "description": "Used for automated repository creation and pre-push commits.",
        },
        "render": {
            "name": "Render",
            "configured": bool(cfg.render_api_key),
            "status": "configured" if cfg.render_api_key else "not_configured",
            "description": "Target cloud deployment platform for hosting FastAPI services.",
        },
    }


@app.get("/settings")
async def get_app_settings():
    """Retrieve non-sensitive application settings and operational metadata."""
    cfg = get_settings()
    return {
        "environment": cfg.environment,
        "max_upload_size_mb": cfg.max_upload_size_bytes // (1024 * 1024),
        "workspace_ttl_seconds": cfg.workspace_ttl_seconds,
        "default_platform": "Render",
        "gemini_model": cfg.gemini_model,
        "gitleaks_configured": bool(cfg.gitleaks_path or shutil.which("gitleaks")),
        "score_deductions": {
            "high": 30,
            "medium": 15,
            "low": 5,
        },
    }


