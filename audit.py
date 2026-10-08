"""Saksham Project Audit Module.

Secret scanning (files and git history via gitleaks), configuration checks,
and Deploy Readiness Score calculation per TASKS.md T10-T13 and RULES.md section 7.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Set, Tuple

from config import ISSUE_SEVERITY_DEDUCTIONS, Settings, get_settings
from redact import redact_text
from schemas import Issue, SeverityEnum

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GITLEAKS_CONFIG = BASE_DIR / "templates" / "gitleaks.toml"

# Central severity mapping table (easy to adjust at T13)
DEFAULT_CHECK_SEVERITIES = {
    "secret_leak": SeverityEnum.HIGH,
    "secret_leak_history": SeverityEnum.HIGH,
    "missing_gitignore_env": SeverityEnum.MEDIUM,
    "hardcoded_localhost": SeverityEnum.MEDIUM,
    "debug_enabled": SeverityEnum.LOW,
    "hardcoded_port": SeverityEnum.MEDIUM,
    "junk_files": SeverityEnum.LOW,
}

JUNK_TARGETS = {
    "node_modules",
    "venv",
    ".venv",
    ".DS_Store",
    "__pycache__",
    ".pytest_cache",
    ".coverage",
    "Thumbs.db",
}


class AuditError(Exception):
    """Base exception for audit and secret scanning failures."""
    pass


class GitleaksNotFoundError(AuditError):
    """Raised when the gitleaks executable cannot be found on the system."""
    pass


def get_gitleaks_binary_path(settings: Optional[Settings] = None) -> Optional[str]:
    """Locate the gitleaks executable using config, PATH, or system paths.

    Args:
        settings: Application settings for optional GITLEAKS_PATH override.

    Returns:
        Optional[str]: Absolute path to gitleaks binary if found, else None.
    """
    cfg = settings or get_settings()

    # 1. Check custom GITLEAKS_PATH from configuration/env
    if cfg.gitleaks_path:
        custom_path = Path(cfg.gitleaks_path)
        if custom_path.is_file():
            return str(custom_path)

    # 2. Check standard system PATH via shutil.which
    path_from_which = shutil.which("gitleaks")
    if path_from_which:
        return path_from_which

    # 3. Check Windows WinGet standard installation directory
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        winget_pattern = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pattern.is_dir():
            for gitleaks_candidate in winget_pattern.glob("**/gitleaks.exe"):
                if gitleaks_candidate.is_file():
                    return str(gitleaks_candidate)

    return None


def _ensure_gitleaks_config(config_path: Optional[Path] = None) -> Path:
    """Ensure Saksham's own Gitleaks configuration file exists."""
    effective_config = config_path or DEFAULT_GITLEAKS_CONFIG
    if not effective_config.is_file():
        effective_config.parent.mkdir(parents=True, exist_ok=True)
        effective_config.write_text(
            'title = "Saksham Gitleaks Rules"\n\n[extend]\nuseDefault = true\n',
            encoding="utf-8",
        )
    return effective_config


def scan_secrets(
    project_dir: Path,
    timeout_seconds: int = 30,
    config_path: Optional[Path] = None,
    settings: Optional[Settings] = None,
) -> List[Issue]:
    """Scan working tree files in a project directory for hardcoded secrets.

    Args:
        project_dir: Path to the target project directory.
        timeout_seconds: Subprocess timeout in seconds.
        config_path: Custom Gitleaks config path.
        settings: Application settings.

    Returns:
        List[Issue]: Detected secret issues in current files (High severity).
    """
    gitleaks_bin = get_gitleaks_binary_path(settings=settings)
    if not gitleaks_bin:
        raise GitleaksNotFoundError(
            "gitleaks binary not found on system PATH. Please ensure gitleaks is installed."
        )

    project_path = Path(project_dir).resolve()
    if not project_path.is_dir():
        raise AuditError(f"Target scan directory does not exist: {project_path}")

    effective_config = _ensure_gitleaks_config(config_path)

    temp_audit_dir = Path(tempfile.mkdtemp(prefix="saksham_audit_"))
    report_file = temp_audit_dir / "gitleaks_report.json"
    dummy_ignore_file = temp_audit_dir / "empty.gitleaksignore"
    dummy_ignore_file.write_text("", encoding="utf-8")

    cmd_args = [
        gitleaks_bin,
        "detect",
        "--source",
        str(project_path),
        "--no-git",
        "--redact",
        "--ignore-gitleaks-allow",
        "--config",
        str(effective_config.resolve()),
        "--gitleaks-ignore-path",
        str(dummy_ignore_file.resolve()),
        "--report-format",
        "json",
        "--report-path",
        str(report_file.resolve()),
        "--exit-code",
        "1",
    ]

    try:
        proc = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )

        if proc.returncode > 1:
            error_msg = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
            raise AuditError(f"Gitleaks execution failed: {error_msg}")

        if not report_file.is_file():
            return []

        report_content = report_file.read_text(encoding="utf-8", errors="ignore").strip()
        if not report_content:
            return []

        try:
            raw_findings = json.loads(report_content)
        except json.JSONDecodeError as exc:
            raise AuditError(f"Failed to parse Gitleaks JSON output: {exc}")

        issues: List[Issue] = []
        for finding in raw_findings:
            raw_file = finding.get("File", "")
            try:
                rel_file = Path(raw_file).resolve().relative_to(project_path)
                file_str = str(rel_file).replace("\\", "/")
            except ValueError:
                file_str = raw_file.replace("\\", "/")

            line_num = int(finding.get("StartLine", 0))
            rule_id = finding.get("RuleID", "generic-secret")
            description = finding.get("Description", "Hardcoded secret detected")

            explanation = redact_text(
                f"Hardcoded secret detected matching rule '{rule_id}': {description}."
            )

            issues.append(
                Issue(
                    severity=DEFAULT_CHECK_SEVERITIES["secret_leak"],
                    title=f"Hardcoded secret ({rule_id})",
                    file=file_str,
                    line=line_num,
                    explanation=explanation,
                )
            )

        return issues

    except subprocess.TimeoutExpired:
        raise AuditError(f"Gitleaks scan timed out after {timeout_seconds} seconds.")
    finally:
        if temp_audit_dir.exists():
            shutil.rmtree(temp_audit_dir, ignore_errors=True)


def scan_git_history(
    project_dir: Path,
    history_available: bool = True,
    timeout_seconds: int = 30,
    config_path: Optional[Path] = None,
    settings: Optional[Settings] = None,
    current_file_issues: Optional[List[Issue]] = None,
) -> Tuple[List[Issue], str]:
    """Scan git commit history for leaked secrets.

    Args:
        project_dir: Target project directory path.
        history_available: Flag indicating whether .git history was preserved.
        timeout_seconds: Subprocess timeout in seconds.
        config_path: Custom Gitleaks config path.
        settings: Application settings.
        current_file_issues: File issues from scan_secrets used for de-duplication.

    Returns:
        Tuple[List[Issue], str]: Discovered history issues and status description.
    """
    project_path = Path(project_dir).resolve()
    git_dir = project_path / ".git"

    if not history_available or not git_dir.is_dir():
        return [], "history not available"

    gitleaks_bin = get_gitleaks_binary_path(settings=settings)
    if not gitleaks_bin:
        raise GitleaksNotFoundError(
            "gitleaks binary not found on system PATH. Please ensure gitleaks is installed."
        )

    effective_config = _ensure_gitleaks_config(config_path)

    temp_audit_dir = Path(tempfile.mkdtemp(prefix="saksham_history_audit_"))
    report_file = temp_audit_dir / "gitleaks_history_report.json"
    dummy_ignore_file = temp_audit_dir / "empty.gitleaksignore"
    dummy_ignore_file.write_text("", encoding="utf-8")

    # Run in git mode on the project directory
    cmd_args = [
        gitleaks_bin,
        "detect",
        "--source",
        str(project_path),
        "--redact",
        "--ignore-gitleaks-allow",
        "--config",
        str(effective_config.resolve()),
        "--gitleaks-ignore-path",
        str(dummy_ignore_file.resolve()),
        "--report-format",
        "json",
        "--report-path",
        str(report_file.resolve()),
        "--exit-code",
        "1",
    ]

    # Configure environment to handle Git 2.35.2+ safe directory strictly scoped to project_path
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "safe.directory"
    env["GIT_CONFIG_VALUE_0"] = str(project_path.resolve())

    try:
        proc = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            env=env,
        )

        if proc.returncode > 1:
            error_msg = proc.stderr.strip() or proc.stdout.strip()
            if "dubious ownership" in error_msg.lower():
                # Handle dubious ownership gracefully if safe.directory fails
                return [], "history scan skipped (git safe.directory restricted)"
            raise AuditError(f"Gitleaks git history scan failed: {error_msg}")

        if not report_file.is_file():
            return [], "history scanned"

        report_content = report_file.read_text(encoding="utf-8", errors="ignore").strip()
        if not report_content:
            return [], "history scanned"

        try:
            raw_findings = json.loads(report_content)
        except json.JSONDecodeError as exc:
            raise AuditError(f"Failed to parse Gitleaks history JSON output: {exc}")

        # Collect fingerprints or (file, line) pairs of existing file issues for de-duplication
        existing_keys: Set[str] = set()
        if current_file_issues:
            for iss in current_file_issues:
                existing_keys.add(f"{iss.file}:{iss.line}")

        history_issues: List[Issue] = []
        for finding in raw_findings:
            raw_file = finding.get("File", "")
            try:
                rel_file = Path(raw_file).resolve().relative_to(project_path)
                file_str = str(rel_file).replace("\\", "/")
            except ValueError:
                file_str = raw_file.replace("\\", "/")

            line_num = int(finding.get("StartLine", 0))
            rule_id = finding.get("RuleID", "generic-secret")
            description = finding.get("Description", "Hardcoded secret detected")
            commit_raw = finding.get("Commit", "")
            short_commit = commit_raw[:7] if commit_raw else "unknown"

            # De-duplication: if finding matches an active current file issue, do not duplicate
            current_key = f"{file_str}:{line_num}"
            if current_key in existing_keys and not commit_raw:
                continue

            explanation = redact_text(
                f"Hardcoded secret detected in git history (commit {short_commit}) "
                f"matching rule '{rule_id}': {description}."
            )

            history_issues.append(
                Issue(
                    severity=DEFAULT_CHECK_SEVERITIES["secret_leak_history"],
                    title=f"Hardcoded secret in git history ({rule_id})",
                    file=file_str,
                    line=line_num,
                    explanation=explanation,
                )
            )

        return history_issues, "history scanned"

    except subprocess.TimeoutExpired:
        raise AuditError(f"Gitleaks history scan timed out after {timeout_seconds} seconds.")
    finally:
        if temp_audit_dir.exists():
            shutil.rmtree(temp_audit_dir, ignore_errors=True)


def check_env_in_gitignore(project_dir: Path) -> List[Issue]:
    """Check that .env and environment variable files are ignored in .gitignore."""
    issues: List[Issue] = []
    project_path = Path(project_dir).resolve()
    gitignore_path = project_path / ".gitignore"

    if not gitignore_path.is_file():
        issues.append(
            Issue(
                severity=DEFAULT_CHECK_SEVERITIES["missing_gitignore_env"],
                title="Missing .gitignore file",
                file=".gitignore",
                line=0,
                explanation=".gitignore file is missing. Sensitive environment files (.env) could be committed to git.",
            )
        )
        return issues

    try:
        content = gitignore_path.read_text(encoding="utf-8", errors="ignore")
        ignored_patterns = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        has_env = any(
            re.search(r"^\.?env(\.\*|\*|\/|$)", pat) or pat in {".env", ".env.*", "*.env", ".env.local"}
            for pat in ignored_patterns
        )

        if not has_env:
            issues.append(
                Issue(
                    severity=DEFAULT_CHECK_SEVERITIES["missing_gitignore_env"],
                    title="Environment file .env not in .gitignore",
                    file=".gitignore",
                    line=0,
                    explanation=".env is not listed in .gitignore. Secrets and environment credentials could be leaked into source control.",
                )
            )
    except Exception:
        pass

    return issues


def check_hardcoded_localhost(project_dir: Path) -> List[Issue]:
    """Check for hardcoded localhost or 127.0.0.1 bind addresses."""
    issues: List[Issue] = []
    project_path = Path(project_dir).resolve()

    for py_file in project_path.rglob("*.py"):
        if any(junk in py_file.parts for junk in JUNK_TARGETS):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            rel_file = str(py_file.relative_to(project_path)).replace("\\", "/")

            # AST or text search for host="127.0.0.1" or host='localhost'
            for idx, line in enumerate(content.splitlines(), start=1):
                if re.search(r"""\bhost\s*=\s*['"](?:127\.0\.0\.1|localhost)['"]""", line):
                    issues.append(
                        Issue(
                            severity=DEFAULT_CHECK_SEVERITIES["hardcoded_localhost"],
                            title="Hardcoded localhost / 127.0.0.1 bind host",
                            file=rel_file,
                            line=idx,
                            explanation="Application is hardcoded to bind to 127.0.0.1/localhost. Render web services require binding to 0.0.0.0 (or os.getenv('HOST', '0.0.0.0')) to receive incoming internet traffic.",
                        )
                    )
        except Exception:
            pass

    return issues


def check_debug_enabled(project_dir: Path) -> List[Issue]:
    """Check for debug or development reload mode enabled in production code."""
    issues: List[Issue] = []
    project_path = Path(project_dir).resolve()

    for py_file in project_path.rglob("*.py"):
        if any(junk in py_file.parts for junk in JUNK_TARGETS):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            rel_file = str(py_file.relative_to(project_path)).replace("\\", "/")

            for idx, line in enumerate(content.splitlines(), start=1):
                # Match DEBUG = True, debug=True, or reload=True in production entrypoints
                if re.search(r"""\bDEBUG\s*=\s*True\b""", line) or re.search(r"""\b(?:debug|reload)\s*=\s*True\b""", line):
                    issues.append(
                        Issue(
                            severity=DEFAULT_CHECK_SEVERITIES["debug_enabled"],
                            title="Debug / Reload mode enabled",
                            file=rel_file,
                            line=idx,
                            explanation="Debug or automatic reload mode is enabled in code. In production, debug mode exposes internal stack traces and degrades performance.",
                        )
                    )
        except Exception:
            pass

    return issues


def check_hardcoded_port(project_dir: Path) -> List[Issue]:
    """Check for hardcoded server port numbers without PORT env fallback."""
    issues: List[Issue] = []
    project_path = Path(project_dir).resolve()

    for py_file in project_path.rglob("*.py"):
        if any(junk in py_file.parts for junk in JUNK_TARGETS):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            rel_file = str(py_file.relative_to(project_path)).replace("\\", "/")

            for idx, line in enumerate(content.splitlines(), start=1):
                # Match port=8000 (direct integer literal in uvicorn.run or app startup)
                if re.search(r"""\bport\s*=\s*[0-9]{2,5}\b""", line) and "os.getenv" not in line and "environ" not in line:
                    issues.append(
                        Issue(
                            severity=DEFAULT_CHECK_SEVERITIES["hardcoded_port"],
                            title="Hardcoded server port",
                            file=rel_file,
                            line=idx,
                            explanation="Server port is hardcoded to a fixed integer. Cloud platforms like Render assign ports dynamically via the PORT environment variable (e.g., int(os.getenv('PORT', 8000))).",
                        )
                    )
        except Exception:
            pass

    return issues


def check_junk_files(project_dir: Path) -> List[Issue]:
    """Check for unnecessary junk directories and cache files committed in project."""
    issues: List[Issue] = []
    project_path = Path(project_dir).resolve()

    for path in project_path.rglob("*"):
        if path.name in JUNK_TARGETS:
            try:
                rel_path = str(path.relative_to(project_path)).replace("\\", "/")
            except ValueError:
                rel_path = path.name

            issues.append(
                Issue(
                    severity=DEFAULT_CHECK_SEVERITIES["junk_files"],
                    title=f"Unnecessary junk file/directory: {path.name}",
                    file=rel_path,
                    line=0,
                    explanation=f"Temporary, build, or cache artifact '{path.name}' should not be committed to source control.",
                )
            )

    return issues


def calculate_readiness_score(
    issues: List[Issue],
    weights: Optional[dict] = None,
) -> Tuple[int, List[str]]:
    """Calculate Deploy Readiness Score (0-100) based on detected issues.

    Deductions: High -30, Medium -15, Low -5. Clamped between 0 and 100.

    Args:
        issues: List of detected security/config issues.
        weights: Optional dictionary mapping SeverityEnum to integer deduction values.

    Returns:
        Tuple[int, List[str]]: Calculated final score and itemized deduction reasons.
    """
    effective_weights = weights or ISSUE_SEVERITY_DEDUCTIONS
    total_deduction = 0
    reasons: List[str] = []

    for issue in issues:
        deduction = effective_weights.get(issue.severity, 0)
        total_deduction += deduction
        line_info = f":{issue.line}" if issue.line > 0 else ""
        reasons.append(
            f"-{deduction} [{issue.severity.value}] {issue.title} in {issue.file}{line_info}"
        )

    final_score = max(0, min(100, 100 - total_deduction))
    return final_score, reasons


def audit_project(
    project_dir: Path,
    history_available: bool = True,
    settings: Optional[Settings] = None,
) -> Tuple[List[Issue], int, List[str], str]:
    """Run comprehensive project audit: secrets, git history, and configuration checks.

    Args:
        project_dir: Root project directory.
        history_available: Whether git history is present.
        settings: Application settings.

    Returns:
        Tuple[List[Issue], int, List[str], str]: Issues, readiness score, deduction reasons, and git history status.
    """
    issues: List[Issue] = []

    # 1. Secret scan in current files (T10)
    file_secret_issues = scan_secrets(project_dir, settings=settings)
    issues.extend(file_secret_issues)

    # 2. Git history scan (T11)
    history_issues, history_status = scan_git_history(
        project_dir,
        history_available=history_available,
        settings=settings,
        current_file_issues=file_secret_issues,
    )
    issues.extend(history_issues)

    # 3. Config checks (T12)
    issues.extend(check_env_in_gitignore(project_dir))
    issues.extend(check_hardcoded_localhost(project_dir))
    issues.extend(check_debug_enabled(project_dir))
    issues.extend(check_hardcoded_port(project_dir))
    issues.extend(check_junk_files(project_dir))

    score, reasons = calculate_readiness_score(issues)

    return issues, score, reasons, history_status
