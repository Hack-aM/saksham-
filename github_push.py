"""Saksham GitHub Integration Module.

Handles GitHub Personal Access Token validation, new repository creation (via PyGithub),
safe pre-push secret scanning gate, git commit, and pushing (via GitPython) per
ARCHITECTURE.md section 8 and TASKS.md T05, T20.

Strict Security:
- Tokens and secrets are never logged, stored in plain text, or returned in API responses.
- Creates NEW repositories only; never deletes or modifies existing user repositories.
- Never force-pushes.
- Pre-push secret gate blocks push if any High-severity secrets remain.
- Strictly excludes .env, saksham.db, .pem, .key, and gitignored artifacts.
- Scopes safe.directory strictly to the workspace directory without mutating global git config.
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from github import Auth, BadCredentialsException, Github, GithubException
from git import GitCommandError, Repo

from audit import audit_project
from config import Settings, get_settings
from redact import redact_text
from schemas import SeverityEnum

REQUIRED_SCOPES: Set[str] = {"repo", "workflow"}
REPO_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")
FORBIDDEN_STAGED_PATTERNS = [
    re.compile(r"""(^|/)\.env(\..+)?$""", re.IGNORECASE),
    re.compile(r"""(^|/)saksham\.db$""", re.IGNORECASE),
    re.compile(r"""\.(pem|key|pfx|p12)$""", re.IGNORECASE),
]


class GitHubPushError(Exception):
    """Base exception for GitHub repository creation and push failures."""
    pass


class GitHubTokenError(GitHubPushError):
    """Raised when GitHub token validation fails."""
    pass


def validate_repo_name(repo_name: str) -> str:
    """Validate repository name format and safety.

    Args:
        repo_name: Proposed repository name.

    Returns:
        str: Sanitized, validated repository name.

    Raises:
        GitHubPushError: If repository name contains invalid characters or escapes.
    """
    cleaned = (repo_name or "").strip()
    if not cleaned:
        raise GitHubPushError("Repository name cannot be empty.")

    if cleaned in {".", ".."} or not REPO_NAME_REGEX.match(cleaned):
        raise GitHubPushError(
            f"Invalid repository name: '{repo_name}'. Name must be 1-100 characters containing "
            f"only letters, numbers, hyphens, periods, or underscores."
        )

    return cleaned


def validate_github_token(
    token: Optional[str] = None,
    timeout_seconds: int = 10,
) -> Dict[str, object]:
    """Validate a GitHub Personal Access Token and verify its required scopes.

    Verifies authentication against the GitHub API and checks for 'repo' and 'workflow'
    permissions required for repo creation and deployment workflow management.

    Args:
        token: Personal Access Token string. Defaults to settings.github_token.
        timeout_seconds: Connection timeout in seconds.

    Returns:
        dict: {
            "valid": bool,
            "username": str,
            "scopes": List[str],
            "message": str
        }

    Raises:
        GitHubTokenError: If validation fails due to invalid credentials, missing scopes, or API error.
    """
    token_to_check = token if token is not None else get_settings().github_token
    token_to_check = token_to_check.strip() if token_to_check else ""

    if not token_to_check:
        raise GitHubTokenError(
            "GitHub token is missing. Please set GITHUB_TOKEN in your .env or configuration."
        )

    if token_to_check.startswith("github_pat_"):
        raise GitHubTokenError(
            "Fine-grained Personal Access Tokens are not supported. Use a classic token with repo and workflow scopes."
        )

    try:
        auth = Auth.Token(token_to_check)
        gh = Github(auth=auth, timeout=timeout_seconds)

        # Verify authenticated user
        user = gh.get_user()
        username = user.login

        # Retrieve OAuth scopes from API response headers
        oauth_scopes_raw = getattr(gh, "oauth_scopes", None)
        if oauth_scopes_raw is None:
            headers = getattr(user, "raw_headers", {}) or {}
            scopes_header = headers.get("x-oauth-scopes", "")
            scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]
        else:
            scopes = [s.strip() for s in oauth_scopes_raw if s.strip()]

        if not scopes:
            raise GitHubTokenError(
                "No OAuth scopes detected on token. Use a classic token with repo and workflow scopes."
            )

        scope_set = set(scopes)
        missing_scopes = REQUIRED_SCOPES - scope_set

        if missing_scopes:
            raise GitHubTokenError(
                f"GitHub token for user '{username}' is missing required scopes: {', '.join(sorted(missing_scopes))}. "
                f"Required scopes: {', '.join(sorted(REQUIRED_SCOPES))}."
            )

        return {
            "valid": True,
            "username": username,
            "scopes": scopes,
            "message": f"Successfully authenticated as GitHub user '{username}'.",
        }

    except BadCredentialsException:
        raise GitHubTokenError("Invalid GitHub Personal Access Token (Bad Credentials).")
    except GithubException as exc:
        sanitized_msg = redact_text(str(exc.data if hasattr(exc, "data") else str(exc)))
        raise GitHubTokenError(f"GitHub API error: {sanitized_msg}")
    except GitHubTokenError:
        raise
    except Exception as exc:
        sanitized_msg = redact_text(str(exc))
        raise GitHubTokenError(f"Failed to validate GitHub token: {sanitized_msg}")


def create_remote_repo(
    token: str,
    repo_name: str,
    private: bool = False,
    description: str = "Deployed with Saksham",
    timeout_seconds: int = 15,
    max_retries: int = 2,
) -> Dict[str, str]:
    """Create a new remote GitHub repository under the authenticated user account.

    Enforces:
    - NEW repositories only (raises error if repository already exists).
    - NEVER deletes repositories.
    - Transient retry support (up to max_retries).

    Args:
        token: GitHub Personal Access Token.
        repo_name: Name of the repository to create.
        private: Whether repository is private (default: False/public).
        description: Repository description string.
        timeout_seconds: Connection timeout in seconds.
        max_retries: Retry attempts for transient errors.

    Returns:
        dict: {
            "repo_name": str,
            "html_url": str,
            "clone_url": str,
            "private": bool,
        }

    Raises:
        GitHubPushError: If repository exists, name is invalid, or creation fails.
    """
    valid_name = validate_repo_name(repo_name)
    auth = Auth.Token(token)
    gh = Github(auth=auth, timeout=timeout_seconds)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            user = gh.get_user()

            # Check if repo already exists to prevent overwriting or pushing to existing repos
            try:
                existing_repo = user.get_repo(valid_name)
                if existing_repo:
                    raise GitHubPushError(
                        f"Repository '{valid_name}' already exists for user '{user.login}'. "
                        f"Saksham only creates new repositories to prevent modifying existing projects."
                    )
            except GithubException as e:
                # 404 Not Found is expected and indicates repo does not exist yet
                if e.status != 404:
                    raise

            # Create new repository
            repo = user.create_repo(
                name=valid_name,
                description=description,
                private=private,
                auto_init=False,
            )

            return {
                "repo_name": repo.name,
                "html_url": repo.html_url,
                "clone_url": repo.clone_url,
                "private": repo.private,
            }

        except GitHubPushError:
            raise
        except BadCredentialsException:
            raise GitHubTokenError("Invalid GitHub Personal Access Token.")
        except GithubException as e:
            last_error = e
            sanitized = redact_text(str(e.data if hasattr(e, "data") else str(e)))
            if e.status == 422:
                raise GitHubPushError(f"GitHub repository creation rejected: {sanitized}")
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise GitHubPushError(f"GitHub API error ({e.status}): {sanitized}") from e
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise GitHubPushError(f"Failed to create GitHub repository: {redact_text(str(e))}") from e

    raise GitHubPushError(f"Failed to create repository after retries: {redact_text(str(last_error))}")


def pre_push_secret_check(workspace_dir: Path, settings: Optional[Settings] = None) -> None:
    """Execute final security audit scan on the workspace before committing or pushing.

    Raises:
        GitHubPushError: If any High-severity secret leaks are detected.
    """
    workspace_path = Path(workspace_dir).resolve()
    issues, score, _, _ = audit_project(workspace_path, history_available=False, settings=settings)

    high_secret_issues = [
        issue for issue in issues if issue.severity == SeverityEnum.HIGH
    ]

    if high_secret_issues:
        first_issue = high_secret_issues[0]
        raise GitHubPushError(
            f"Pre-push secret check failed: High-severity secret leak detected "
            f"('{first_issue.title}' in '{first_issue.file}'). Push aborted to protect credentials."
        )


def commit_and_push_workspace(
    workspace_dir: Path,
    repo_clone_url: str,
    token: str,
    commit_message: str = "Initial commit by Saksham",
    branch: str = "main",
) -> str:
    """Stage, commit, and push the prepared workspace to the remote GitHub repository.

    Enforces:
    - Strictly excludes .env, saksham.db, and secret files.
    - Scopes safe.directory to workspace_dir for the subprocess.
    - Never uses force-push.
    - Cleans token from remote URL immediately after push.

    Args:
        workspace_dir: Path to the isolated project workspace directory.
        repo_clone_url: HTTPS clone URL of the created GitHub repository.
        token: GitHub Personal Access Token for authentication.
        commit_message: Commit message string.
        branch: Target branch name (default: 'main').

    Returns:
        str: Short commit hash (7 characters).

    Raises:
        GitHubPushError: If git staging, commit, or push fails.
    """
    workspace_path = Path(workspace_dir).resolve()
    if not workspace_path.is_dir():
        raise GitHubPushError(f"Workspace directory does not exist: {workspace_path}")

    # Configure safe.directory environment strictly for this workspace
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "safe.directory"
    env["GIT_CONFIG_VALUE_0"] = str(workspace_path)

    try:
        # Initialize or load git repository in workspace
        git_dir = workspace_path / ".git"
        if not git_dir.is_dir():
            repo = Repo.init(str(workspace_path))
        else:
            repo = Repo(str(workspace_path))

        repo.git.custom_environment(**env)

        # Configure local git author inside workspace .git/config (does not modify global config)
        with repo.config_writer() as config:
            config.set_value("user", "name", "Saksham Agent")
            config.set_value("user", "email", "agent@saksham.local")

        # Stage all files respecting .gitignore
        repo.git.add(all=True)

        # Security check: verify no forbidden secret files were accidentally staged
        staged_files = repo.git.diff("--cached", "--name-only").splitlines()
        for staged in staged_files:
            for pattern in FORBIDDEN_STAGED_PATTERNS:
                if pattern.search(staged):
                    raise GitHubPushError(
                        f"Security violation: Forbidden secret file '{staged}' was staged for commit. Push aborted."
                    )

        # Commit changes
        if repo.is_dirty(untracked_files=True) or len(staged_files) > 0:
            repo.git.commit("-m", commit_message)

        # Set branch name to main
        try:
            repo.git.branch("-M", branch)
        except GitCommandError:
            pass

        # Configure authenticated remote URL for push
        authenticated_url = repo_clone_url.replace(
            "https://",
            f"https://x-access-token:{token}@",
        )

        if "origin" in [r.name for r in repo.remotes]:
            origin = repo.remote("origin")
            origin.set_url(authenticated_url)
        else:
            origin = repo.create_remote("origin", authenticated_url)

        # Push to remote (Never force-push)
        try:
            repo.git.push("-u", "origin", branch)
        finally:
            # Immediately sanitize remote URL in local git config so token is not retained
            try:
                origin.set_url(repo_clone_url)
            except Exception:
                pass

        commit_sha = repo.head.commit.hexsha[:7] if repo.head.is_valid() else "initial"
        return commit_sha

    except GitCommandError as e:
        sanitized_err = redact_text(str(e), custom_secrets=[token])
        raise GitHubPushError(f"Git operation failed: {sanitized_err}") from e
    except GitHubPushError:
        raise
    except Exception as e:
        sanitized_err = redact_text(str(e), custom_secrets=[token])
        raise GitHubPushError(f"Failed to push workspace to GitHub: {sanitized_err}") from e


def push_workspace_to_github(
    workspace_dir: Path,
    repo_name: str,
    token: Optional[str] = None,
    private: bool = False,
    description: str = "Deployed with Saksham",
    settings: Optional[Settings] = None,
) -> Dict[str, str]:
    """Complete GitHub pipeline: token validation -> pre-push secret scan -> new repo creation -> git commit & push.

    Args:
        workspace_dir: Path to the workspace directory.
        repo_name: Desired name for the new GitHub repository.
        token: Optional GitHub Personal Access Token.
        private: Whether the new repository should be private.
        description: Description for the new repository.
        settings: Application settings.

    Returns:
        dict: {
            "repo_url": str,
            "clone_url": str,
            "commit_sha": str,
            "repo_name": str,
            "private": bool,
        }

    Raises:
        GitHubPushError: If validation, secret check, repo creation, or push fails.
    """
    cfg = settings or get_settings()
    effective_token = token if token is not None else cfg.github_token
    effective_token = effective_token.strip() if effective_token else ""

    # 1. Validate token and identity
    validate_github_token(effective_token)

    # 2. Final pre-push secret audit scan
    pre_push_secret_check(workspace_dir, settings=cfg)

    # 3. Create NEW repository on GitHub
    repo_info = create_remote_repo(
        token=effective_token,
        repo_name=repo_name,
        private=private,
        description=description,
    )

    # 4. Git commit and push workspace
    commit_sha = commit_and_push_workspace(
        workspace_dir=workspace_dir,
        repo_clone_url=repo_info["clone_url"],
        token=effective_token,
    )

    return {
        "repo_url": repo_info["html_url"],
        "clone_url": repo_info["clone_url"],
        "commit_sha": commit_sha,
        "repo_name": repo_info["repo_name"],
        "private": repo_info["private"],
    }
