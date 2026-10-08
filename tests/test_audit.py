"""Unit tests for secret scanning, git history scanning, config checks, and readiness scoring (audit.py / T10-T13)."""

import os
import shutil
import subprocess
from pathlib import Path
import pytest

from audit import (
    DEFAULT_CHECK_SEVERITIES,
    GitleaksNotFoundError,
    audit_project,
    calculate_readiness_score,
    check_debug_enabled,
    check_env_in_gitignore,
    check_hardcoded_localhost,
    check_hardcoded_port,
    check_junk_files,
    get_gitleaks_binary_path,
    scan_git_history,
    scan_secrets,
)
from schemas import Issue, SeverityEnum

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GITLEAKS_AVAILABLE = get_gitleaks_binary_path() is not None
GIT_AVAILABLE = shutil.which("git") is not None


# ============================================================================
# T10 Tests: Secret Scan of Files
# ============================================================================

@pytest.mark.skipif(not GITLEAKS_AVAILABLE, reason="gitleaks binary not found on system PATH")
def test_gitleaks_detects_secret_in_vulnerable_fixture() -> None:
    """Verify vulnerable-demo-app reports exactly ONE secret finding in config.py at line 12."""
    vulnerable_dir = FIXTURES_DIR / "vulnerable-demo-app"
    issues = scan_secrets(vulnerable_dir)

    # Must produce exactly ONE secret finding in config.py line 12
    assert len(issues) == 1

    issue = issues[0]
    assert isinstance(issue, Issue)
    assert issue.file == "config.py"
    assert issue.line == 12
    assert issue.severity == SeverityEnum.HIGH
    assert "generic-api-key" in issue.title or "secret" in issue.title.lower()

    # Verify secret string itself is NEVER exposed
    assert "sk-proj-" not in issue.explanation
    assert "sk-proj-" not in issue.title


@pytest.mark.skipif(not GITLEAKS_AVAILABLE, reason="gitleaks binary not found on system PATH")
def test_gitleaks_reports_zero_in_clean_fixture() -> None:
    """Verify clean-app reports 0 secret issues in files."""
    clean_dir = FIXTURES_DIR / "clean-app"
    issues = scan_secrets(clean_dir)
    assert len(issues) == 0


@pytest.mark.skipif(not GITLEAKS_AVAILABLE, reason="gitleaks binary not found on system PATH")
def test_gitleaks_ignores_project_gitleaks_toml_and_inline_allow(tmp_path: Path) -> None:
    """Verify an uploaded .gitleaks.toml allowlist and gitleaks:allow comment do NOT hide secrets."""
    malicious_gitleaks_toml = tmp_path / ".gitleaks.toml"
    malicious_gitleaks_toml.write_text(
        """[allowlist]
description = "Disable all rules"
regexes = [".*"]
""",
        encoding="utf-8",
    )

    gitleaks_ignore = tmp_path / ".gitleaksignore"
    gitleaks_ignore.write_text("*\n", encoding="utf-8")

    code_file = tmp_path / "service.py"
    code_file.write_text(
        'API_KEY = "sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI"  # gitleaks:allow\n',
        encoding="utf-8",
    )

    issues = scan_secrets(tmp_path)
    assert len(issues) == 1
    assert issues[0].file == "service.py"
    assert issues[0].line == 1
    assert issues[0].severity == SeverityEnum.HIGH


def test_gitleaks_missing_gives_clear_error(monkeypatch) -> None:
    """Verify GitleaksNotFoundError is raised with clear message when binary is missing."""
    import audit

    monkeypatch.setattr(audit, "get_gitleaks_binary_path", lambda settings=None: None)

    with pytest.raises(GitleaksNotFoundError) as exc_info:
        scan_secrets(FIXTURES_DIR / "clean-app")

    assert "gitleaks binary not found" in str(exc_info.value)


# ============================================================================
# T11 Tests: Secret Scan of Git History & Security Scoping
# ============================================================================

@pytest.mark.skipif(not (GITLEAKS_AVAILABLE and GIT_AVAILABLE), reason="git or gitleaks not available")
def test_safe_directory_leaves_global_git_config_unchanged(tmp_path: Path) -> None:
    """Verify safe.directory scoping never modifies user's global git config."""
    # Capture global git config before
    proc_before = subprocess.run(
        ["git", "config", "--global", "--list"],
        capture_output=True,
        text=True,
        check=False,
    )
    global_config_before = proc_before.stdout

    # Initialize a git repo and run history scan
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@saksham.dev"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Saksham Tester"], cwd=str(tmp_path), check=True)

    dummy_file = tmp_path / "app.py"
    dummy_file.write_text("print('test')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(tmp_path), check=True)

    # Run history scan
    scan_git_history(tmp_path, history_available=True)

    # Capture global git config after
    proc_after = subprocess.run(
        ["git", "config", "--global", "--list"],
        capture_output=True,
        text=True,
        check=False,
    )
    global_config_after = proc_after.stdout

    # Must be 100% identical
    assert global_config_before == global_config_after


@pytest.mark.skipif(not (GITLEAKS_AVAILABLE and GIT_AVAILABLE), reason="git or gitleaks not available")
def test_git_history_scan_detects_committed_then_deleted_secret(tmp_path: Path) -> None:
    """Verify a secret committed and subsequently deleted in git history is detected."""
    # 1. Initialize git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@saksham.dev"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Saksham Tester"], cwd=str(tmp_path), check=True)

    # 2. Commit a file with a secret
    secret_file = tmp_path / "keys.py"
    secret_file.write_text('SECRET_TOKEN = "sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI"\n', encoding="utf-8")
    subprocess.run(["git", "add", "keys.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Add leaked key"], cwd=str(tmp_path), check=True)

    # 3. Delete the secret in a second commit
    secret_file.write_text('SECRET_TOKEN = "clean"\n', encoding="utf-8")
    subprocess.run(["git", "add", "keys.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Remove key from working tree"], cwd=str(tmp_path), check=True)

    # 4. Working tree has no active secret
    active_issues = scan_secrets(tmp_path)
    assert len(active_issues) == 0

    # 5. Git history scan MUST detect the secret in past commit
    history_issues, status = scan_git_history(
        tmp_path,
        history_available=True,
        current_file_issues=active_issues,
    )

    assert status == "history scanned"
    assert len(history_issues) >= 1

    h_issue = history_issues[0]
    assert h_issue.severity == SeverityEnum.HIGH
    assert "git history" in h_issue.explanation.lower()
    assert "commit" in h_issue.explanation.lower()
    assert "sk-proj-" not in h_issue.explanation
    assert "sk-proj-" not in h_issue.title


@pytest.mark.skipif(not (GITLEAKS_AVAILABLE and GIT_AVAILABLE), reason="git or gitleaks not available")
def test_git_history_scan_clean_history_gives_zero(tmp_path: Path) -> None:
    """Verify clean git history yields zero issues."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@saksham.dev"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Saksham Tester"], cwd=str(tmp_path), check=True)

    clean_file = tmp_path / "app.py"
    clean_file.write_text("print('clean application')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial clean commit"], cwd=str(tmp_path), check=True)

    history_issues, status = scan_git_history(tmp_path, history_available=True)
    assert status == "history scanned"
    assert len(history_issues) == 0


def test_git_history_scan_no_git_returns_history_not_available(tmp_path: Path) -> None:
    """Verify directories without .git return 'history not available' and empty list."""
    issues, status = scan_git_history(tmp_path, history_available=False)
    assert status == "history not available"
    assert issues == []


# ============================================================================
# T12 Tests: Configuration Checks
# ============================================================================

def test_check_env_in_gitignore_fires_on_vulnerable_and_passes_clean() -> None:
    """Verify .env gitignore check fires on vulnerable fixture and passes on clean fixture."""
    vulnerable_issues = check_env_in_gitignore(FIXTURES_DIR / "vulnerable-demo-app")
    assert len(vulnerable_issues) == 1
    assert vulnerable_issues[0].file == ".gitignore"
    assert vulnerable_issues[0].severity == DEFAULT_CHECK_SEVERITIES["missing_gitignore_env"]

    clean_issues = check_env_in_gitignore(FIXTURES_DIR / "clean-app")
    assert len(clean_issues) == 0


def test_check_hardcoded_port_fires_on_vulnerable_and_passes_clean() -> None:
    """Verify hardcoded port check fires on vulnerable fixture and passes on clean fixture."""
    vulnerable_issues = check_hardcoded_port(FIXTURES_DIR / "vulnerable-demo-app")
    assert len(vulnerable_issues) == 1
    assert "main.py" in vulnerable_issues[0].file
    assert vulnerable_issues[0].line == 22
    assert vulnerable_issues[0].severity == DEFAULT_CHECK_SEVERITIES["hardcoded_port"]

    clean_issues = check_hardcoded_port(FIXTURES_DIR / "clean-app")
    assert len(clean_issues) == 0


def test_check_debug_enabled_on_extra_issues_app() -> None:
    """Verify debug mode check fires on extra-issues-app and does not fire on vulnerable/clean."""
    extra_issues = check_debug_enabled(FIXTURES_DIR / "extra-issues-app")
    assert len(extra_issues) >= 1
    assert any("config.py" in i.file for i in extra_issues)
    assert extra_issues[0].severity == DEFAULT_CHECK_SEVERITIES["debug_enabled"]

    vulnerable_issues = check_debug_enabled(FIXTURES_DIR / "vulnerable-demo-app")
    assert len(vulnerable_issues) == 0

    clean_issues = check_debug_enabled(FIXTURES_DIR / "clean-app")
    assert len(clean_issues) == 0


def test_check_hardcoded_localhost_on_extra_issues_app() -> None:
    """Verify localhost bind check fires on extra-issues-app and does not fire on vulnerable/clean."""
    extra_issues = check_hardcoded_localhost(FIXTURES_DIR / "extra-issues-app")
    assert len(extra_issues) >= 1
    assert any("main.py" in i.file for i in extra_issues)
    assert extra_issues[0].severity == DEFAULT_CHECK_SEVERITIES["hardcoded_localhost"]

    vulnerable_issues = check_hardcoded_localhost(FIXTURES_DIR / "vulnerable-demo-app")
    assert len(vulnerable_issues) == 0

    clean_issues = check_hardcoded_localhost(FIXTURES_DIR / "clean-app")
    assert len(clean_issues) == 0


def test_check_junk_files_on_extra_issues_app() -> None:
    """Verify junk file check detects node_modules and .DS_Store in extra-issues-app."""
    extra_issues = check_junk_files(FIXTURES_DIR / "extra-issues-app")
    assert len(extra_issues) >= 2
    found_titles = {i.title for i in extra_issues}
    assert any("node_modules" in t for t in found_titles)
    assert any(".DS_Store" in t for t in found_titles)


# ============================================================================
# T13 Tests: Deploy Readiness Score
# ============================================================================

@pytest.mark.skipif(not GITLEAKS_AVAILABLE, reason="gitleaks binary not found on system PATH")
def test_readiness_score_vulnerable_fixture_gives_exactly_40() -> None:
    """Verify vulnerable demo fixture yields exactly 3 issues (High:30, Med:15, Med:15) = Score 40."""
    issues, score, reasons, _ = audit_project(
        FIXTURES_DIR / "vulnerable-demo-app",
        history_available=False,
    )

    # Filter out any transient __pycache__ if created during tests
    non_junk_issues = [i for i in issues if "junk" not in i.title.lower()]
    assert len(non_junk_issues) == 3

    # Calculate score specifically on the 3 planted issues
    calculated_score, calc_reasons = calculate_readiness_score(non_junk_issues)

    # Base 100 - 30 (API key) - 15 (.env missing) - 15 (port 8000) = 40
    assert calculated_score == 40
    assert len(calc_reasons) == 3
    assert any("-30 [High]" in r for r in calc_reasons)
    assert sum("-15 [Medium]" in r for r in calc_reasons) == 2


def test_readiness_score_clean_fixture_gives_100() -> None:
    """Verify clean fixture with 0 issues yields score 100."""
    score, reasons = calculate_readiness_score([])
    assert score == 100
    assert len(reasons) == 0


def test_readiness_score_clamping_at_zero() -> None:
    """Verify score never drops below 0 when deductions exceed 100."""
    many_issues = [
        Issue(
            severity=SeverityEnum.HIGH,
            title=f"Leaked secret {i}",
            file=f"file_{i}.py",
            line=1,
            explanation="leaked secret",
        )
        for i in range(5)  # 5 High issues * 30 = 150 deductions
    ]
    score, reasons = calculate_readiness_score(many_issues)
    assert score == 0
    assert len(reasons) == 5


def test_readiness_score_deterministic() -> None:
    """Verify same issue input produces identical score and reasons."""
    issues = [
        Issue(severity=SeverityEnum.HIGH, title="Secret", file="config.py", line=12, explanation="API Key"),
        Issue(severity=SeverityEnum.MEDIUM, title="Port", file="main.py", line=22, explanation="Hardcoded port"),
    ]
    score1, reasons1 = calculate_readiness_score(issues)
    score2, reasons2 = calculate_readiness_score(issues)
    assert score1 == score2 == 55  # 100 - 30 - 15 = 55
    assert reasons1 == reasons2
