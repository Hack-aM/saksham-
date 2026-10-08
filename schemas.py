"""Saksham Pydantic Schemas Module.

Data transfer objects and validation models for Issues, Patches, Analysis Results,
and Deploy Results per ARCHITECTURE.md section 8 and TASKS.md T07.

Field Mapping to db.py SQLite tables:
- Issue: id, analysis_id, severity, title, file, line, explanation -> issues table
- Patch: id, analysis_id, issue_id, file, old (mapped to old_content in DB), new (mapped to new_content in DB), reason, status -> patches table
- AnalysisResult: id, project_name, stack, score, created_at -> analyses table
- DeployResult: id, analysis_id, repo_url, live_url, platform, health_status, final_score, logs, created_at -> deployments table
"""

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class SeverityEnum(str, Enum):
    """Severity levels for detected issues."""
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class PatchStatusEnum(str, Enum):
    """Lifecycle status of a proposed code patch."""
    SUGGESTED = "suggested"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"


class ScanResult(BaseModel):
    """Model representing rule-based stack and project detection results."""
    stack: str = Field(..., description="Detected stack description (e.g. 'Python / FastAPI' or 'unknown').")
    language: str = Field(default="unknown", description="Detected language (e.g. 'Python', 'Node.js', 'unknown').")
    framework: str = Field(default="unknown", description="Detected web framework (e.g. 'FastAPI', 'unknown').")
    entry_point: Optional[str] = Field(default=None, description="Detected entry point script (e.g. 'main.py').")
    port: int = Field(default=8000, description="Detected server port or 8000 default.")
    dependencies: List[str] = Field(default_factory=list, description="Extracted dependencies.")
    supported: bool = Field(default=True, description="Whether this stack is supported in MVP.")
    message: Optional[str] = Field(default=None, description="User-facing detection or unsupported message.")


class Issue(BaseModel):
    """Model representing an audited security or configuration issue."""
    id: Optional[str] = None
    severity: SeverityEnum = Field(
        ...,
        description="Issue severity level: High (e.g. leaked secret), Medium (e.g. .env not gitignored), Low."
    )
    title: str = Field(..., min_length=1, description="Concise description of the problem.")
    file: str = Field(..., min_length=1, description="File path relative to project root.")
    line: int = Field(default=0, ge=0, description="1-indexed line number (0 if file-level).")
    explanation: str = Field(..., min_length=1, description="Beginner-friendly explanation.")


class Patch(BaseModel):
    """Model representing an LLM-suggested structured code modification."""
    id: Optional[str] = None
    issue_id: Optional[str] = Field(default=None, description="ID of the issue this patch fixes.")
    file: str = Field(..., min_length=1, description="Target file path.")
    old: str = Field(..., description="Exact original code string to be replaced (mapped to old_content in db.py).")
    new: str = Field(..., description="Replacement code string (mapped to new_content in db.py).")
    reason: str = Field(..., min_length=1, description="Plain English reason for the proposed change.")
    status: PatchStatusEnum = Field(default=PatchStatusEnum.SUGGESTED, description="Current patch status.")


class AnalysisResult(BaseModel):
    """Model representing the complete scan, audit, and auto-fix analysis."""
    id: Optional[str] = None
    run_id: Optional[str] = Field(default=None, description="Unique workspace run ID.")
    project_name: str = Field(default="project", min_length=1, description="Uploaded project name.")
    stack: str = Field(..., min_length=1, description="Detected language/framework stack.")
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Deploy Readiness Score (0-100). High issues -30, Medium -15, Low -5 from 100."
    )
    reasons: List[str] = Field(default_factory=list, description="Itemized score deduction reasons.")
    issues: List[Issue] = Field(default_factory=list, description="List of detected audit issues.")
    patches: List[Patch] = Field(default_factory=list, description="List of suggested fixes.")
    history_status: Optional[str] = Field(default=None, description="Git history scan status.")
    created_at: Optional[str] = None


class DeployResult(BaseModel):
    """Model representing post-deploy verification and live status."""
    id: Optional[str] = None
    analysis_id: str = Field(..., min_length=1, description="Associated analysis run ID.")
    repo_url: str = Field(..., min_length=1, description="Created GitHub repository URL.")
    live_url: str = Field(..., min_length=1, description="Live deployed service URL.")
    platform: str = Field(default="Render", description="Target cloud platform.")
    health_status: str = Field(..., min_length=1, description="Health check status (e.g. 200 OK).")
    final_score: int = Field(..., ge=0, le=100, description="Post-deploy score (0-100).")
    logs: str = Field(default="", description="Deployment and health check logs.")
    created_at: Optional[str] = None


class ApproveRequest(BaseModel):
    """Request payload for POST /approve endpoint."""
    run_id: str = Field(..., min_length=1, description="Workspace run ID returned from /analyze.")
    approved_patch_ids: List[str] = Field(default_factory=list, description="List of patch IDs approved by user.")
    repo_name: Optional[str] = Field(default=None, description="Target GitHub repository name.")
    visibility: str = Field(default="public", description="GitHub repository visibility (public or private).")


class ApproveResponse(BaseModel):
    """Response payload for POST /approve endpoint."""
    status: str = Field(..., description="Approval status: 'applied', 'blocked', or 'ready'.")
    run_id: str = Field(..., description="Workspace run ID.")
    applied_patches_count: int = Field(default=0, ge=0, description="Number of patches applied.")
    score: int = Field(..., ge=0, le=100, description="Updated Deploy Readiness Score after patches.")
    remaining_issues: List[Issue] = Field(default_factory=list, description="Remaining issues after patch application.")
    message: str = Field(..., description="Status explanation or blocked warning.")


class StageEnum(str, Enum):
    """Pipeline stages for progress tracking and event streaming."""
    UPLOAD = "upload"
    SCAN = "scan"
    AUDIT = "audit"
    FIX = "fix"
    APPROVE = "approve"
    GITHUB = "github"
    DEPLOY = "deploy"
    VERIFY = "verify"
    SELF_FIX = "self_fix"
    COMPLETE = "complete"
    ERROR = "error"


class ProgressEvent(BaseModel):
    """Data model for safe Server-Sent Events (SSE) progress streaming."""
    run_id: str = Field(..., description="Associated workspace run ID.")
    stage: str = Field(..., description="Current pipeline stage name.")
    status: str = Field(..., description="Stage status ('started', 'in_progress', 'completed', 'failed', 'blocked').")
    message: str = Field(..., description="Sanitized, beginner-friendly progress message.")
    percentage: Optional[int] = Field(default=None, ge=0, le=100, description="Progress percentage (0-100).")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp.")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Optional safe stage metadata.")
