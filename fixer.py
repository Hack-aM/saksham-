"""Saksham Fixer Module.

Generates safe, structured, reviewable Patch proposals for audited issues.
Uses deterministic templates for standard config issues and calls GeminiLLMClient
via llm.py for LLM-assisted patches.
Strict Security:
- Provider-agnostic (uses llm.py, does not import Google SDK directly).
- Never sends raw secrets to the LLM (redacts all context).
- Never sends the whole project (sends only relevant file snippet).
- Enforces safe file boundaries (no absolute paths, no .. traversal, no shell command injections).
- Never modifies files on disk in T16 (read-only proposals).
per ARCHITECTURE.md section 8 and TASKS.md T16.
"""

import difflib
import os
import re
import uuid
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from config import get_settings
from llm import GeminiLLMClient, LLMError, LLMResponseError, get_llm_client
from redact import redact_text
from schemas import Issue, Patch, PatchStatusEnum


class FixerError(Exception):
    """Base exception for fixer and patch generation errors."""
    pass


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def render_template(
    template_name: str,
    context: Optional[dict[str, str]] = None,
    templates_dir: Optional[Path] = None,
) -> str:
    """Render a deterministic starter template by name with optional variable substitution.

    Does not call any LLM or execute untrusted code.

    Args:
        template_name: Template filename (e.g. 'Dockerfile.template', 'gitignore.template').
        context: Optional dictionary of key-value replacements.
        templates_dir: Optional custom templates directory.

    Returns:
        str: Rendered template text.

    Raises:
        FixerError: If the template file does not exist.
    """
    base = templates_dir or TEMPLATES_DIR
    template_file = base / template_name
    if not template_file.is_file():
        raise FixerError(f"Template '{template_name}' not found in {base}.")

    content = template_file.read_text(encoding="utf-8")
    if context:
        for key, val in context.items():
            content = content.replace(f"{{{{ {key} }}}}", val)
            content = content.replace(f"{{{{{key}}}}}", val)
    return content


def propose_missing_file_patches(
    workspace_dir: Path,
    project_name: str = "project",
    entry_point: str = "main",
    templates_dir: Optional[Path] = None,
) -> List[Patch]:
    """Propose deterministic starter patches for standard missing project files.

    Generates Patch objects with status SUGGESTED for missing files:
    - .gitignore
    - .env.example
    - Dockerfile
    - .github/workflows/ci.yml
    - README.md

    Does NOT write files to disk.

    Args:
        workspace_dir: Root project directory.
        project_name: Project name for README/templates.
        entry_point: Script entry point stem (e.g. 'main').
        templates_dir: Optional custom templates directory.

    Returns:
        List[Patch]: Proposed new-file patches.
    """
    workspace_path = Path(workspace_dir).resolve()
    patches: List[Patch] = []
    ctx = {
        "project_name": project_name,
        "entry_point": Path(entry_point).stem if entry_point else "main",
    }

    # 1. Missing .gitignore
    gitignore_path = workspace_path / ".gitignore"
    if not gitignore_path.exists():
        content = render_template("gitignore.template", templates_dir=templates_dir)
        patches.append(
            Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                file=".gitignore",
                old="",
                new=content,
                reason="Add standard .gitignore to prevent local secrets (.env) and Python artifacts from being committed.",
                status=PatchStatusEnum.SUGGESTED,
            )
        )

    # 2. Missing .env.example
    env_example_path = workspace_path / ".env.example"
    if not env_example_path.exists():
        content = render_template("env_example.template", templates_dir=templates_dir)
        patches.append(
            Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                file=".env.example",
                old="",
                new=content,
                reason="Add .env.example template documenting required environment variables without committing secrets.",
                status=PatchStatusEnum.SUGGESTED,
            )
        )

    # 3. Missing Dockerfile
    dockerfile_path = workspace_path / "Dockerfile"
    if not dockerfile_path.exists():
        content = render_template("Dockerfile.template", templates_dir=templates_dir)
        patches.append(
            Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                file="Dockerfile",
                old="",
                new=content,
                reason="Add production Dockerfile for containerized deployment on Render.",
                status=PatchStatusEnum.SUGGESTED,
            )
        )

    # 4. Missing GitHub Actions CI workflow
    ci_workflow_path = workspace_path / ".github" / "workflows" / "ci.yml"
    if not ci_workflow_path.exists():
        content = render_template("ci.yml.template", templates_dir=templates_dir)
        patches.append(
            Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                file=".github/workflows/ci.yml",
                old="",
                new=content,
                reason="Add GitHub Actions CI workflow for automated testing and lint verification.",
                status=PatchStatusEnum.SUGGESTED,
            )
        )

    # 5. Missing README.md
    readme_path = workspace_path / "README.md"
    if not readme_path.exists():
        content = render_template("README.md.template", context=ctx, templates_dir=templates_dir)
        patches.append(
            Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                file="README.md",
                old="",
                new=content,
                reason="Add project README with setup and execution instructions.",
                status=PatchStatusEnum.SUGGESTED,
            )
        )

    return patches


class InvalidPatchError(FixerError):
    """Raised when a generated patch violates security or path boundaries."""
    pass


class PatchLLMResponse(BaseModel):
    """Structured response model for LLM patch generation."""
    file: str = Field(..., min_length=1, description="Relative file path.")
    old: str = Field(..., description="Exact original code snippet to replace.")
    new: str = Field(..., description="Replacement code snippet.")
    reason: str = Field(..., min_length=1, description="Plain-English explanation of why this fix is needed.")


DANGEROUS_PATTERNS = [
    re.compile(r"""\bos\.system\s*\(""", re.IGNORECASE),
    re.compile(r"""\bsubprocess\.(?:Popen|call|run|check_output)\s*\(\s*['"][^'"]*(?:rm\s+-rf|del\s+|format\s+|curl\s+|wget\s+)""", re.IGNORECASE),
    re.compile(r"""\b(?:powershell|cmd\.exe|/bin/sh|/bin/bash)\b""", re.IGNORECASE),
]


def validate_patch_safety(patch: Patch, workspace_dir: Path) -> None:
    """Validate that a patch stays strictly within workspace boundaries and does not contain unsafe syntax.

    Args:
        patch: Proposed Patch object.
        workspace_dir: Project directory root.

    Raises:
        InvalidPatchError: If path traversal, absolute paths, or dangerous commands are detected.
    """
    raw_file = patch.file
    norm_file = raw_file.replace("\\", "/")

    # 1. Reject absolute paths or Windows drive letters
    if norm_file.startswith("/") or (len(norm_file) >= 2 and norm_file[1] == ":"):
        raise InvalidPatchError(f"Patch references unsafe absolute file path: '{raw_file}'")

    # 2. Reject path traversal
    parts = norm_file.split("/")
    if ".." in parts or any(p.startswith("..") for p in parts):
        raise InvalidPatchError(f"Patch references path traversal: '{raw_file}'")

    # 3. Check resolved target path stays within workspace boundary
    workspace_path = Path(workspace_dir).resolve()
    target_path = (workspace_path / norm_file).resolve()
    try:
        target_path.relative_to(workspace_path)
    except ValueError:
        raise InvalidPatchError(f"Patch path '{raw_file}' escapes workspace boundary.")

    # 4. Reject dangerous shell injection commands in new patch content
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(patch.new):
            raise InvalidPatchError(f"Patch contains dangerous command execution syntax: '{patch.new}'")


def _read_file_snippet(file_path: Path, target_line: int, window: int = 15) -> str:
    """Read a small window of lines around target_line for LLM context."""
    if not file_path.is_file():
        return ""
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        start = max(0, target_line - window - 1)
        end = min(len(lines), target_line + window)
        return "\n".join(lines[start:end])
    except Exception:
        return ""


def _propose_deterministic_patch(issue: Issue, workspace_dir: Path) -> Optional[Patch]:
    """Generate a deterministic patch for known configuration issues without calling LLM."""
    workspace_path = Path(workspace_dir).resolve()
    target_file = workspace_path / issue.file

    # 1. Missing .env in .gitignore
    if ".env is not listed in .gitignore" in issue.explanation or issue.title == "Missing .gitignore entry for .env":
        gitignore_path = workspace_path / ".gitignore"
        if gitignore_path.is_file():
            existing = gitignore_path.read_text(encoding="utf-8", errors="ignore")
            # If already has .env, no patch needed
            if ".env" in [line.strip() for line in existing.splitlines()]:
                return None
            new_content = existing.rstrip() + "\n.env\n.env.local\n" if existing else ".env\n.env.local\n"
            return Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                issue_id=issue.id,
                file=".gitignore",
                old=existing,
                new=new_content,
                reason="Add .env and .env.local to .gitignore so sensitive environment credentials are never committed to git.",
                status=PatchStatusEnum.SUGGESTED,
            )
        else:
            return Patch(
                id=f"patch-{uuid.uuid4().hex[:8]}",
                issue_id=issue.id,
                file=".gitignore",
                old="",
                new=".env\n.env.local\n__pycache__/\n*.pyc\n",
                reason="Create .gitignore with .env and cache exclusions to protect local secrets from being committed.",
                status=PatchStatusEnum.SUGGESTED,
            )

    # 2. Hardcoded localhost bind host
    if "127.0.0.1" in issue.title or "localhost" in issue.title.lower() or "127.0.0.1" in issue.explanation:
        if target_file.is_file():
            content = target_file.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"""host\s*=\s*['"](?:127\.0\.0\.1|localhost)['"]""", content)
            if match:
                old_str = match.group(0)
                new_str = 'host="0.0.0.0"'
                return Patch(
                    id=f"patch-{uuid.uuid4().hex[:8]}",
                    issue_id=issue.id,
                    file=issue.file,
                    old=old_str,
                    new=new_str,
                    reason="Change bind host from 127.0.0.1/localhost to 0.0.0.0 so the deployed container can receive incoming web traffic on Render.",
                    status=PatchStatusEnum.SUGGESTED,
                )

    # 3. Debug mode enabled
    if "Debug" in issue.title or "debug" in issue.title.lower():
        if target_file.is_file():
            content = target_file.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"""\bDEBUG\s*=\s*True\b""", content)
            if match:
                return Patch(
                    id=f"patch-{uuid.uuid4().hex[:8]}",
                    issue_id=issue.id,
                    file=issue.file,
                    old=match.group(0),
                    new='DEBUG = os.getenv("DEBUG", "False").lower() == "true"',
                    reason="Disable hardcoded debug mode in production to avoid exposing internal stack traces and degrading performance.",
                    status=PatchStatusEnum.SUGGESTED,
                )

    # 4. Hardcoded port without PORT env fallback
    if "Hardcoded server port" in issue.title or "port" in issue.title.lower():
        if target_file.is_file():
            content = target_file.read_text(encoding="utf-8", errors="ignore")
            # Case A: uvicorn.run("main:app", host="0.0.0.0", port=8000, ...)
            match_uvicorn = re.search(r"""uvicorn\.run\([^)]*port\s*=\s*(\d+)[^)]*\)""", content)
            if match_uvicorn:
                old_call = match_uvicorn.group(0)
                port_num = match_uvicorn.group(1)
                # Replace port=8000 with port=int(os.getenv("PORT", "8000"))
                new_call = re.sub(r"""port\s*=\s*\d+""", f'port=int(os.getenv("PORT", "{port_num}"))', old_call)
                return Patch(
                    id=f"patch-{uuid.uuid4().hex[:8]}",
                    issue_id=issue.id,
                    file=issue.file,
                    old=old_call,
                    new=new_call,
                    reason=f"Read server port from os.getenv('PORT', '{port_num}') so the service binds to the dynamic port assigned by Render.",
                    status=PatchStatusEnum.SUGGESTED,
                )
            # Case B: PORT = 8000 assignment
            match_port_assign = re.search(r"""\bPORT\s*=\s*(\d+)\b""", content)
            if match_port_assign:
                port_num = match_port_assign.group(1)
                return Patch(
                    id=f"patch-{uuid.uuid4().hex[:8]}",
                    issue_id=issue.id,
                    file=issue.file,
                    old=match_port_assign.group(0),
                    new=f'PORT = int(os.getenv("PORT", "{port_num}"))',
                    reason=f"Read server port from os.getenv('PORT', '{port_num}') for cloud platform compatibility.",
                    status=PatchStatusEnum.SUGGESTED,
                )

    # 5. Secret leak in active file: Move assignment to os.getenv without inventing secrets
    if "secret" in issue.title.lower() or "api key" in issue.title.lower() or "secret" in issue.explanation.lower():
        # Do not patch if it's history-only (cannot patch working tree for history leaks)
        if "history" in issue.explanation.lower() or "commit" in issue.explanation.lower():
            return None

        if target_file.is_file():
            content = target_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            if 1 <= issue.line <= len(lines):
                target_line_content = lines[issue.line - 1]
                # Match e.g. API_KEY = "..." or SECRET_KEY = "..."
                assign_match = re.match(r"""^\s*([A-Za-z0-9_]+)\s*=\s*['"][^'"]+['"]\s*$""", target_line_content)
                if assign_match:
                    var_name = assign_match.group(1)
                    leading_ws = len(target_line_content) - len(target_line_content.lstrip())
                    indent = target_line_content[:leading_ws]
                    new_line = f'{indent}{var_name} = os.getenv("{var_name}", "")'
                    return Patch(
                        id=f"patch-{uuid.uuid4().hex[:8]}",
                        issue_id=issue.id,
                        file=issue.file,
                        old=target_line_content,
                        new=new_line,
                        reason=f"Move hardcoded secret '{var_name}' to os.getenv('{var_name}') so credentials are loaded safely from environment variables.",
                        status=PatchStatusEnum.SUGGESTED,
                    )

    return None


def propose_patch_for_issue(
    issue: Issue,
    workspace_dir: Path,
    llm_client: Optional[GeminiLLMClient] = None,
) -> Optional[Patch]:
    """Generate a single validated Patch proposal for an Issue.

    Tries deterministic template first. If not applicable and llm_client is available,
    calls LLM with sanitized context and validates the structured response.

    Args:
        issue: Issue to resolve.
        workspace_dir: Project directory root.
        llm_client: Optional GeminiLLMClient instance.

    Returns:
        Optional[Patch]: Validated Patch proposal, or None if no patch is applicable.

    Raises:
        InvalidPatchError: If generated patch fails security validation.
    """
    workspace_path = Path(workspace_dir).resolve()

    # 1. Try deterministic fix first (PRD requirement: prefer deterministic fixes for known issues)
    det_patch = _propose_deterministic_patch(issue, workspace_path)
    if det_patch:
        validate_patch_safety(det_patch, workspace_path)
        return det_patch

    # 2. If deterministic fix is not applicable and LLM client is not provided, return None
    if not llm_client:
        return None

    # History findings should not be patched via working tree
    if "history" in issue.explanation.lower() or "commit" in issue.explanation.lower():
        return None

    target_file = workspace_path / issue.file
    if not target_file.is_file():
        return None

    # 3. Read and sanitize file context (Never send raw secrets to LLM)
    raw_snippet = _read_file_snippet(target_file, issue.line)
    sanitized_snippet = redact_text(raw_snippet)
    sanitized_explanation = redact_text(issue.explanation)

    system_instruction = (
        "You are an expert security and configuration code fixer for Python/FastAPI web applications.\n"
        "Your task is to propose a minimal, safe code replacement that resolves the reported issue.\n"
        "STRICT SECURITY RULES:\n"
        "1. NEVER invent or generate replacement API keys, passwords, or secret tokens. Always replace hardcoded secrets with os.getenv('VAR_NAME', '').\n"
        "2. The 'old' field MUST EXACTLY MATCH the code substring in the provided snippet to be replaced.\n"
        "3. The 'new' field must contain the replacement code only.\n"
        "4. The 'file' field must match the relative file path.\n"
        "5. Never output shell commands, dangerous scripts, or system calls.\n"
    )

    prompt = (
        f"Audited Issue: {sanitized_explanation}\n"
        f"Target File: {issue.file}\n"
        f"Line: {issue.line}\n\n"
        f"File Snippet (Sanitized):\n```\n{sanitized_snippet}\n```\n\n"
        f"Propose a structured JSON patch to fix this issue."
    )

    try:
        llm_res: PatchLLMResponse = llm_client.generate_structured(
            prompt=prompt,
            response_model=PatchLLMResponse,
            system_instruction=system_instruction,
            temperature=0.1,
        )

        patch = Patch(
            id=f"patch-{uuid.uuid4().hex[:8]}",
            issue_id=issue.id,
            file=issue.file,
            old=llm_res.old,
            new=llm_res.new,
            reason=llm_res.reason,
            status=PatchStatusEnum.SUGGESTED,
        )

        # Validate security boundaries
        validate_patch_safety(patch, workspace_path)
        return patch
    except (LLMResponseError, LLMError) as e:
        # LLM failure should fail safely without crashing the fixer pipeline
        return None


def propose_patches_for_issues(
    issues: List[Issue],
    workspace_dir: Path,
    llm_client: Optional[GeminiLLMClient] = None,
) -> List[Patch]:
    """Generate safe, validated Patch proposals for all actionable issues.

    Args:
        issues: List of audited issues.
        workspace_dir: Project directory root.
        llm_client: Optional GeminiLLMClient instance.

    Returns:
        List[Patch]: List of valid, proposed Patch objects.
    """
    patches: List[Patch] = []
    workspace_path = Path(workspace_dir).resolve()

    for issue in issues:
        try:
            patch = propose_patch_for_issue(issue, workspace_path, llm_client=llm_client)
            if patch:
                patches.append(patch)
        except InvalidPatchError:
            # Drop unsafe patches safely
            continue

    return patches


class UnapprovedPatchError(FixerError):
    """Raised when an attempt is made to apply an unapproved patch."""
    pass


class PatchMatchError(FixerError):
    """Raised when patch old content does not match the target file content."""
    pass


class PatchApplicationError(FixerError):
    """Raised when patch application fails."""
    pass


def generate_unified_diff(
    old_content: str,
    new_content: str,
    from_file: str = "a/file",
    to_file: str = "b/file",
    redact: bool = True,
) -> str:
    """Generate a clean unified diff string between old and new text.

    Args:
        old_content: Original content string.
        new_content: Modified replacement content string.
        from_file: Display name for original version in diff header.
        to_file: Display name for new version in diff header.
        redact: Whether to mask sensitive values and tokens in the diff.

    Returns:
        str: Formatted unified diff text.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_file,
            tofile=to_file,
        )
    )
    diff_text = "".join(diff_lines)
    if redact:
        diff_text = redact_text(diff_text)
    return diff_text


def generate_patch_diff(
    patch: Patch,
    workspace_dir: Optional[Path] = None,
    redact: bool = True,
) -> str:
    """Generate reviewable unified diff for a single Patch object.

    If workspace_dir is provided and the target file exists, computes the full-file
    diff in memory. Otherwise, produces snippet-level unified diff.

    Args:
        patch: Patch object.
        workspace_dir: Optional project workspace directory.
        redact: Whether to mask sensitive values in the diff.

    Returns:
        str: Unified diff text.
    """
    from_name = f"a/{patch.file}"
    to_name = f"b/{patch.file}"

    if workspace_dir:
        workspace_path = Path(workspace_dir).resolve()
        target_file = workspace_path / patch.file
        if target_file.is_file():
            try:
                original_full = target_file.read_text(encoding="utf-8", errors="ignore")
                if patch.old in original_full:
                    patched_full = original_full.replace(patch.old, patch.new, 1)
                    return generate_unified_diff(
                        original_full, patched_full, from_name, to_name, redact=redact
                    )
            except Exception:
                pass

    return generate_unified_diff(patch.old, patch.new, from_name, to_name, redact=redact)


def apply_patch(patch: Patch, workspace_dir: Path) -> Patch:
    """Safely apply a single approved Patch to the workspace directory.

    Enforces:
    - Patch must have status APPROVED.
    - Path must stay strictly within workspace_dir.
    - No shell commands or subprocess execution.
    - Exact match requirement on 'old' content.
    - Atomic file write replacement.

    Args:
        patch: Approved Patch object.
        workspace_dir: Root workspace directory.

    Returns:
        Patch: Updated Patch with status APPLIED.

    Raises:
        UnapprovedPatchError: If patch status is not APPROVED.
        InvalidPatchError: If patch path or content violates safety boundaries.
        PatchMatchError: If target file does not match patch 'old' content.
    """
    workspace_path = Path(workspace_dir).resolve()
    validate_patch_safety(patch, workspace_path)

    # 1. Require patch status to be APPROVED
    if patch.status != PatchStatusEnum.APPROVED:
        raise UnapprovedPatchError(
            f"Cannot apply patch for '{patch.file}' with status '{patch.status.value}'. "
            f"Patch must be explicitly APPROVED by user before application."
        )

    norm_file = patch.file.replace("\\", "/")
    target_path = (workspace_path / norm_file).resolve()

    # Reject target directories and symlinks
    if target_path.exists():
        if target_path.is_dir():
            raise InvalidPatchError(f"Target path '{patch.file}' is a directory, not a file.")
        if target_path.is_symlink():
            raise InvalidPatchError(f"Target path '{patch.file}' is a symlink.")

    # 2. In-memory modification and exact match validation
    if target_path.is_file():
        current_content = target_path.read_text(encoding="utf-8")
        if patch.old not in current_content:
            raise PatchMatchError(
                f"Cannot apply patch to '{patch.file}': expected 'old' content not found in target file."
            )
        new_content = current_content.replace(patch.old, patch.new, 1)
    else:
        if patch.old != "":
            raise PatchMatchError(
                f"Cannot apply patch to non-existent file '{patch.file}': patch requires non-empty 'old' content."
            )
        new_content = patch.new

    # 3. Atomic file write
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target_path.parent / f".tmp_{uuid.uuid4().hex[:8]}_{target_path.name}"
    try:
        temp_target.write_text(new_content, encoding="utf-8")
        temp_target.replace(target_path)
    except Exception as e:
        if temp_target.exists():
            temp_target.unlink(missing_ok=True)
        raise PatchApplicationError(f"Failed to write patch atomically to '{patch.file}': {e}") from e

    patch.status = PatchStatusEnum.APPLIED
    return patch


def apply_patches(patches: List[Patch], workspace_dir: Path) -> List[Patch]:
    """Safely apply a batch of approved Patches to the workspace directory.

    Transactional / All-or-Nothing validation:
    Simulates all patch applications in memory first. If any patch fails validation,
    approval check, or exact match, the entire batch is aborted without touching disk.

    Args:
        patches: List of approved Patch objects.
        workspace_dir: Root workspace directory.

    Returns:
        List[Patch]: List of updated Patch objects with status APPLIED.

    Raises:
        UnapprovedPatchError: If any patch is not APPROVED.
        InvalidPatchError: If any patch violates safety rules.
        PatchMatchError: If any patch fails exact-content matching.
    """
    workspace_path = Path(workspace_dir).resolve()
    simulated_files: dict[Path, str] = {}

    # Pass 1: Validation & In-Memory Simulation
    for patch in patches:
        validate_patch_safety(patch, workspace_path)
        if patch.status != PatchStatusEnum.APPROVED:
            raise UnapprovedPatchError(
                f"Cannot apply batch: patch for '{patch.file}' has status '{patch.status.value}'. "
                f"All patches in batch must be APPROVED."
            )

        norm_file = patch.file.replace("\\", "/")
        target_path = (workspace_path / norm_file).resolve()

        if target_path.exists():
            if target_path.is_dir():
                raise InvalidPatchError(f"Target path '{patch.file}' is a directory.")
            if target_path.is_symlink():
                raise InvalidPatchError(f"Target path '{patch.file}' is a symlink.")

        if target_path not in simulated_files:
            if target_path.is_file():
                simulated_files[target_path] = target_path.read_text(encoding="utf-8")
            else:
                simulated_files[target_path] = ""

        current_sim = simulated_files[target_path]
        if target_path.is_file() or current_sim != "":
            if patch.old not in current_sim:
                raise PatchMatchError(
                    f"Cannot apply patch to '{patch.file}': expected 'old' content not found."
                )
            simulated_files[target_path] = current_sim.replace(patch.old, patch.new, 1)
        else:
            if patch.old != "":
                raise PatchMatchError(
                    f"Cannot create new file '{patch.file}': patch requires non-empty 'old' content."
                )
            simulated_files[target_path] = patch.new

    # Pass 2: Atomic Disk Writes
    for target_path, final_content in simulated_files.items():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target_path.parent / f".tmp_{uuid.uuid4().hex[:8]}_{target_path.name}"
        try:
            temp_target.write_text(final_content, encoding="utf-8")
            temp_target.replace(target_path)
        except Exception as e:
            if temp_target.exists():
                temp_target.unlink(missing_ok=True)
            raise PatchApplicationError(f"Failed to write patch to '{target_path}': {e}") from e

    # Pass 3: Update statuses
    for patch in patches:
        patch.status = PatchStatusEnum.APPLIED

    return patches
