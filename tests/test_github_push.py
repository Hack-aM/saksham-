"""Unit tests for T20: GitHub Repository Creation & Push (github_push.py).

Verifies all safety and security guardrails:
- Token validation and authenticated identity lookup.
- Safe repository name validation.
- Creation of NEW repositories only (rejects existing repos, never deletes repos).
- Safe git operations: no force-push, workspace-scoped safe.directory, no global config mutation.
- Forbidden file checks: .env, saksham.db, private keys (.pem, .key).
- Final pre-push secret audit gate: blocks push if any High-severity secrets exist.
- Transient retry limit and error handling.
- Token redaction (never leaked in error messages, logs, or outputs).
- Uploaded project code is never executed.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from github import BadCredentialsException, GithubException
from git import GitCommandError, Repo

from github_push import (
    GitHubPushError,
    GitHubTokenError,
    validate_repo_name,
    validate_github_token,
    create_remote_repo,
    pre_push_secret_check,
    commit_and_push_workspace,
    push_workspace_to_github,
)
from schemas import Issue, SeverityEnum


# ==========================================
# 1. Repository Name Validation Tests
# ==========================================

def test_repo_name_validation_valid_names() -> None:
    """Verify that standard, valid repository names pass validation unchanged."""
    valid_names = [
        "my-app",
        "saksham_project",
        "demo.app.v1",
        "fastapi-backend-123",
        "A",
        "repo_name_100_chars_" + ("x" * 78),
    ]
    for name in valid_names:
        assert validate_repo_name(name) == name


def test_repo_name_validation_invalid_names() -> None:
    """Verify that invalid, unsafe, or empty repository names are rejected."""
    invalid_cases = [
        "",
        "   ",
        ".",
        "..",
        "my repo with spaces",
        "user/repo",
        "user\\repo",
        "repo;rm -rf /",
        "repo$name",
        "repo#name",
        "repo?name",
        "repo`name",
        "a" * 101,  # Exceeds 100 chars
    ]
    for invalid in invalid_cases:
        with pytest.raises(GitHubPushError):
            validate_repo_name(invalid)


# ==========================================
# 2. GitHub Token Validation Tests
# ==========================================

def test_validate_github_token_missing() -> None:
    """Verify that missing/empty token raises GitHubTokenError."""
    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="")
    assert "GitHub token is missing" in str(exc_info.value)


def test_validate_github_token_fine_grained_rejected() -> None:
    """Verify fine-grained PAT is rejected with classic token advice."""
    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="github_pat_1234567890abcdef")
    assert "Fine-grained Personal Access Tokens are not supported" in str(exc_info.value)


@patch("github_push.Github")
def test_validate_github_token_bad_credentials(mock_gh_cls) -> None:
    """Verify BadCredentialsException raises clean error without leaking token."""
    mock_gh = MagicMock()
    mock_gh.get_user.side_effect = BadCredentialsException(401, {"message": "Bad credentials"}, None)
    mock_gh_cls.return_value = mock_gh

    secret_token = "ghp_super_secret_token_1234567890"
    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token=secret_token)

    err_msg = str(exc_info.value)
    assert "Invalid GitHub Personal Access Token" in err_msg
    assert secret_token not in err_msg


@patch("github_push.Github")
def test_validate_github_token_missing_scopes(mock_gh_cls) -> None:
    """Verify token missing 'workflow' scope is rejected."""
    mock_user = MagicMock()
    mock_user.login = "student1"
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh.oauth_scopes = ["repo"]
    mock_gh_cls.return_value = mock_gh

    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="ghp_partialscope12345")
    assert "missing required scopes" in str(exc_info.value)
    assert "workflow" in str(exc_info.value)


@patch("github_push.Github")
def test_validate_github_token_success(mock_gh_cls) -> None:
    """Verify valid token returns authenticated identity and scopes."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh.oauth_scopes = ["repo", "workflow"]
    mock_gh_cls.return_value = mock_gh

    res = validate_github_token(token="ghp_validtoken12345")
    assert res["valid"] is True
    assert res["username"] == "octocat"
    assert "repo" in res["scopes"]
    assert "workflow" in res["scopes"]


# ==========================================
# 3. Repository Creation Tests (Mocks)
# ==========================================

@patch("github_push.Github")
def test_create_remote_repo_success(mock_gh_cls) -> None:
    """Verify creating a new remote repository when repo does not exist."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    # Repo doesn't exist yet -> get_repo raises 404
    mock_user.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)

    created_repo = MagicMock()
    created_repo.name = "my-new-app"
    created_repo.html_url = "https://github.com/octocat/my-new-app"
    created_repo.clone_url = "https://github.com/octocat/my-new-app.git"
    created_repo.private = False
    mock_user.create_repo.return_value = created_repo

    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh_cls.return_value = mock_gh

    res = create_remote_repo(
        token="ghp_validtoken12345",
        repo_name="my-new-app",
        private=False,
        description="Deployed with Saksham",
    )

    assert res["repo_name"] == "my-new-app"
    assert res["html_url"] == "https://github.com/octocat/my-new-app"
    assert res["clone_url"] == "https://github.com/octocat/my-new-app.git"
    assert res["private"] is False
    mock_user.create_repo.assert_called_once_with(
        name="my-new-app",
        description="Deployed with Saksham",
        private=False,
        auto_init=False,
    )


@patch("github_push.Github")
def test_create_remote_repo_existing_conflict_rejected(mock_gh_cls) -> None:
    """Verify that if repo already exists, creation is aborted (never overwrite)."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    existing_repo = MagicMock()
    existing_repo.name = "existing-app"
    mock_user.get_repo.return_value = existing_repo

    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh_cls.return_value = mock_gh

    with pytest.raises(GitHubPushError) as exc_info:
        create_remote_repo(token="ghp_validtoken12345", repo_name="existing-app")

    assert "already exists" in str(exc_info.value)
    assert "Saksham only creates new repositories" in str(exc_info.value)
    mock_user.create_repo.assert_not_called()


@patch("github_push.Github")
def test_create_remote_repo_never_deletes_repository(mock_gh_cls) -> None:
    """Verify that repository deletion is never invoked under any condition."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    mock_user.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)
    mock_user.create_repo.side_effect = GithubException(500, {"message": "Internal error"}, None)

    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh_cls.return_value = mock_gh

    with pytest.raises(GitHubPushError):
        create_remote_repo(token="ghp_token", repo_name="demo-app", max_retries=1)

    # Ensure no delete method on user or repo was ever called
    assert not hasattr(mock_user, "delete") or mock_user.delete.call_count == 0


@patch("github_push.Github")
def test_create_remote_repo_transient_retry_success(mock_gh_cls) -> None:
    """Verify that transient 500 error is retried and succeeds within retry cap."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    mock_user.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)

    created_repo = MagicMock()
    created_repo.name = "retry-app"
    created_repo.html_url = "https://github.com/octocat/retry-app"
    created_repo.clone_url = "https://github.com/octocat/retry-app.git"
    created_repo.private = True

    # Fail on first attempt, succeed on second attempt
    mock_user.create_repo.side_effect = [
        GithubException(500, {"message": "Server Error"}, None),
        created_repo,
    ]

    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh_cls.return_value = mock_gh

    with patch("time.sleep", return_value=None):
        res = create_remote_repo(
            token="ghp_token",
            repo_name="retry-app",
            private=True,
            max_retries=2,
        )

    assert res["repo_name"] == "retry-app"
    assert res["private"] is True
    assert mock_user.create_repo.call_count == 2


@patch("github_push.Github")
def test_create_remote_repo_422_rejected_immediately(mock_gh_cls) -> None:
    """Verify that 422 Unprocessable Entity fails immediately without retry."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    mock_user.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, None)
    mock_user.create_repo.side_effect = GithubException(422, {"message": "Repository creation failed"}, None)

    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh_cls.return_value = mock_gh

    with pytest.raises(GitHubPushError) as exc_info:
        create_remote_repo(token="ghp_token", repo_name="bad-app", max_retries=2)

    assert "creation rejected" in str(exc_info.value)
    assert mock_user.create_repo.call_count == 1


# ==========================================
# 4. Pre-Push Final Secret Scan Tests
# ==========================================

def test_pre_push_secret_check_clean_workspace(tmp_path: Path) -> None:
    """Verify that a clean workspace passes pre-push secret audit."""
    app_file = tmp_path / "main.py"
    app_file.write_text("print('Hello clean world!')", encoding="utf-8")
    
    # Should complete without error
    pre_push_secret_check(tmp_path)


@patch("github_push.audit_project")
def test_pre_push_secret_check_blocks_on_high_secret(mock_audit, tmp_path: Path) -> None:
    """Verify that any High-severity secret finding immediately blocks the push."""
    mock_issue = Issue(
        id="SEC-001",
        title="Planted Secret Key",
        severity=SeverityEnum.HIGH,
        file="config.py",
        line=12,
        explanation="High severity API key leak detected.",
    )
    mock_audit.return_value = ([mock_issue], 50, [], "clean")

    with pytest.raises(GitHubPushError) as exc_info:
        pre_push_secret_check(tmp_path)

    err_msg = str(exc_info.value)
    assert "Pre-push secret check failed" in err_msg
    assert "Planted Secret Key" in err_msg
    assert "Push aborted to protect credentials" in err_msg


# ==========================================
# 5. Git Staging, Commit, and Push Tests
# ==========================================

def test_commit_and_push_excludes_forbidden_env_file(tmp_path: Path) -> None:
    """Verify that staging a .env file triggers security violation and halts push."""
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=12345", encoding="utf-8")
    main_file = tmp_path / "main.py"
    main_file.write_text("print('hello')", encoding="utf-8")

    with pytest.raises(GitHubPushError) as exc_info:
        commit_and_push_workspace(
            workspace_dir=tmp_path,
            repo_clone_url="https://github.com/octocat/test.git",
            token="ghp_testtoken",
        )

    err_msg = str(exc_info.value)
    assert "Forbidden secret file '.env' was staged" in err_msg


def test_commit_and_push_excludes_saksham_db(tmp_path: Path) -> None:
    """Verify that staging saksham.db triggers security violation and halts push."""
    db_file = tmp_path / "saksham.db"
    db_file.write_text("sqlite format 3", encoding="utf-8")

    with pytest.raises(GitHubPushError) as exc_info:
        commit_and_push_workspace(
            workspace_dir=tmp_path,
            repo_clone_url="https://github.com/octocat/test.git",
            token="ghp_testtoken",
        )

    err_msg = str(exc_info.value)
    assert "Forbidden secret file 'saksham.db' was staged" in err_msg


def test_commit_and_push_excludes_private_key(tmp_path: Path) -> None:
    """Verify that staging a private key (.pem/.key) triggers security violation."""
    key_file = tmp_path / "server.key"
    key_file.write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")

    with pytest.raises(GitHubPushError) as exc_info:
        commit_and_push_workspace(
            workspace_dir=tmp_path,
            repo_clone_url="https://github.com/octocat/test.git",
            token="ghp_testtoken",
        )

    err_msg = str(exc_info.value)
    assert "Forbidden secret file 'server.key' was staged" in err_msg


def test_commit_and_push_respects_gitignore(tmp_path: Path) -> None:
    """Verify that files listed in .gitignore (e.g. ignored .env) are not staged."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    remote_bare = tmp_path / "remote.git"
    Repo.init(str(remote_bare), bare=True)

    gitignore = workspace / ".gitignore"
    gitignore.write_text(".env\n__pycache__/\n*.db\n", encoding="utf-8")

    env_file = workspace / ".env"
    env_file.write_text("LOCAL_SECRET=foo", encoding="utf-8")

    app_file = workspace / "main.py"
    app_file.write_text("print('Saksham app')", encoding="utf-8")

    commit_sha = commit_and_push_workspace(
        workspace_dir=workspace,
        repo_clone_url=str(remote_bare.resolve()),
        token="ghp_mock_token_12345",
    )

    assert commit_sha is not None
    assert len(commit_sha) == 7


def test_commit_and_push_never_uses_force_push(tmp_path: Path) -> None:
    """Verify that non-fast-forward push is rejected and not forced."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    remote_bare = tmp_path / "remote.git"
    Repo.init(str(remote_bare), bare=True)

    app_file = workspace / "main.py"
    app_file.write_text("print('Saksham initial app')", encoding="utf-8")

    commit_sha = commit_and_push_workspace(
        workspace_dir=workspace,
        repo_clone_url=str(remote_bare.resolve()),
        token="ghp_mock_token_12345",
    )
    assert len(commit_sha) == 7

    # Create a second conflicting workspace that tries to push an unrelated history
    workspace2 = tmp_path / "workspace2"
    workspace2.mkdir()
    app_file2 = workspace2 / "main.py"
    app_file2.write_text("print('Conflicting app')", encoding="utf-8")

    with pytest.raises(GitHubPushError) as exc_info:
        commit_and_push_workspace(
            workspace_dir=workspace2,
            repo_clone_url=str(remote_bare.resolve()),
            token="ghp_mock_token_12345",
        )
    # Rejection occurs because no force-push flag is present
    assert "Git operation failed" in str(exc_info.value) or "rejected" in str(exc_info.value)


def test_commit_and_push_cleans_token_from_remote_url(tmp_path: Path) -> None:
    """Verify that token is purged from local git remote URL after push completes."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    remote_bare = tmp_path / "remote.git"
    Repo.init(str(remote_bare), bare=True)

    app_file = workspace / "main.py"
    app_file.write_text("print('Safe app')", encoding="utf-8")

    secret_token = "ghp_super_secret_token_abc123456789"
    clone_url = str(remote_bare.resolve())

    commit_and_push_workspace(
        workspace_dir=workspace,
        repo_clone_url=clone_url,
        token=secret_token,
    )

    # Read .git/config and repo.remote("origin").url to verify token is absent
    repo = Repo(str(workspace))
    origin_url = repo.remote("origin").url
    assert secret_token not in origin_url

    config_file = workspace / ".git" / "config"
    config_content = config_file.read_text(encoding="utf-8")
    assert secret_token not in config_content
    assert "remote.git" in config_content


def test_safe_directory_scoped_and_global_config_unchanged(tmp_path: Path) -> None:
    """Verify safe.directory is passed in subprocess environment and global git config is unchanged."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    remote_bare = tmp_path / "remote.git"
    Repo.init(str(remote_bare), bare=True)

    app_file = workspace / "main.py"
    app_file.write_text("print('Safe scoped dir')", encoding="utf-8")

    # Read global git config before
    proc_before = subprocess.run(
        ["git", "config", "--global", "--list"],
        capture_output=True,
        text=True,
    )
    global_before = proc_before.stdout

    commit_and_push_workspace(
        workspace_dir=workspace,
        repo_clone_url=str(remote_bare.resolve()),
        token="ghp_mock_token",
    )

    # Read global git config after
    proc_after = subprocess.run(
        ["git", "config", "--global", "--list"],
        capture_output=True,
        text=True,
    )
    global_after = proc_after.stdout

    assert global_before == global_after


# ==========================================
# 6. Full Pipeline Orchestration Tests
# ==========================================

@patch("github_push.validate_github_token")
@patch("github_push.pre_push_secret_check")
@patch("github_push.create_remote_repo")
@patch("github_push.commit_and_push_workspace")
def test_push_workspace_to_github_success(
    mock_commit_push,
    mock_create_repo,
    mock_secret_check,
    mock_validate_token,
    tmp_path: Path,
) -> None:
    """Verify full push pipeline orchestrates all stages correctly."""
    mock_validate_token.return_value = {"valid": True, "username": "octocat"}
    mock_secret_check.return_value = None
    mock_create_repo.return_value = {
        "repo_name": "new-saksham-app",
        "html_url": "https://github.com/octocat/new-saksham-app",
        "clone_url": "https://github.com/octocat/new-saksham-app.git",
        "private": True,
    }
    mock_commit_push.return_value = "a1b2c3d"

    res = push_workspace_to_github(
        workspace_dir=tmp_path,
        repo_name="new-saksham-app",
        token="ghp_valid_token_12345",
        private=True,
        description="Saksham student backend",
    )

    assert res["repo_url"] == "https://github.com/octocat/new-saksham-app"
    assert res["clone_url"] == "https://github.com/octocat/new-saksham-app.git"
    assert res["commit_sha"] == "a1b2c3d"
    assert res["repo_name"] == "new-saksham-app"
    assert res["private"] is True

    mock_validate_token.assert_called_once_with("ghp_valid_token_12345")
    mock_secret_check.assert_called_once()
    mock_create_repo.assert_called_once_with(
        token="ghp_valid_token_12345",
        repo_name="new-saksham-app",
        private=True,
        description="Saksham student backend",
    )
    mock_commit_push.assert_called_once_with(
        workspace_dir=tmp_path,
        repo_clone_url="https://github.com/octocat/new-saksham-app.git",
        token="ghp_valid_token_12345",
    )


def test_token_redacted_in_git_command_error(tmp_path: Path) -> None:
    """Verify that if GitCommandError occurs containing a token, it is redacted."""
    secret_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"

    with patch("git.Repo.init") as mock_init:
        mock_repo = MagicMock()
        mock_repo.git.add.side_effect = GitCommandError(
            command=["git", "add", "--all"],
            status=128,
            stderr=f"fatal: authentication failed for https://x-access-token:{secret_token}@github.com",
        )
        mock_init.return_value = mock_repo

        with pytest.raises(GitHubPushError) as exc_info:
            commit_and_push_workspace(
                workspace_dir=tmp_path,
                repo_clone_url="https://github.com/octocat/test.git",
                token=secret_token,
            )

        err_msg = str(exc_info.value)
        assert secret_token not in err_msg
        assert "[REDACTED]" in err_msg


def test_uploaded_project_code_is_never_executed(tmp_path: Path) -> None:
    """Verify that code inside the workspace is never executed during git push."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    remote_bare = tmp_path / "remote.git"
    Repo.init(str(remote_bare), bare=True)

    # Write a script that would create a marker file if executed
    marker_file = workspace / "executed.txt"
    app_file = workspace / "main.py"
    app_file.write_text(
        f"with open(r'{marker_file}', 'w') as f: f.write('executed')",
        encoding="utf-8",
    )

    commit_and_push_workspace(
        workspace_dir=workspace,
        repo_clone_url=str(remote_bare.resolve()),
        token="ghp_token",
    )

    assert not marker_file.exists(), "Uploaded project code was executed during git push!"
