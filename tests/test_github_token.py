"""Unit tests for GitHub token validation in github_push.py."""

import os
from unittest.mock import MagicMock, patch
import pytest
from github import BadCredentialsException, GithubException
from github_push import validate_github_token, GitHubTokenError


def test_empty_token_raises_error() -> None:
    """Verify that an empty token string immediately raises GitHubTokenError."""
    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="")
    assert "GitHub token is missing" in str(exc_info.value)


@patch("github_push.Github")
def test_invalid_token_bad_credentials(mock_github_cls) -> None:
    """Verify that BadCredentialsException is caught and returned cleanly without leaking token."""
    mock_gh = MagicMock()
    mock_gh.get_user.side_effect = BadCredentialsException(401, {"message": "Bad credentials"}, None)
    mock_github_cls.return_value = mock_gh

    test_token = "ghp_invalidfaketoken1234567890abcdef"
    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token=test_token)
    
    err_msg = str(exc_info.value)
    assert "Invalid GitHub Personal Access Token" in err_msg
    # Ensure token does not appear in error message
    assert test_token not in err_msg


def test_fine_grained_token_rejected() -> None:
    """Verify that fine-grained tokens (github_pat_ prefix) are rejected with a clear message."""
    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="github_pat_11AABC1234567890abcdefghijklmnopqrstuvwxyz_1234567890")
    
    err_msg = str(exc_info.value)
    assert "Use a classic token with repo and workflow scopes" in err_msg


@patch("github_push.Github")
def test_no_scopes_detected_rejected(mock_github_cls) -> None:
    """Verify that a token exposing zero scopes is rejected with the classic token recommendation."""
    mock_user = MagicMock()
    mock_user.login = "testuser"
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh.oauth_scopes = []
    mock_github_cls.return_value = mock_gh

    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="ghp_noscopes1234567890abcdef")
    
    assert "Use a classic token with repo and workflow scopes" in str(exc_info.value)


@patch("github_push.Github")
def test_missing_scopes_raises_error(mock_github_cls) -> None:
    """Verify that a token missing required scopes (e.g. missing 'workflow') raises GitHubTokenError."""
    mock_user = MagicMock()
    mock_user.login = "testuser"
    
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh.oauth_scopes = ["repo"]  # Missing 'workflow'
    mock_github_cls.return_value = mock_gh

    with pytest.raises(GitHubTokenError) as exc_info:
        validate_github_token(token="ghp_partialscope1234567890abcdef")
    
    err_msg = str(exc_info.value)
    assert "missing required scopes" in err_msg
    assert "workflow" in err_msg


@patch("github_push.Github")
def test_valid_token_with_required_scopes(mock_github_cls) -> None:
    """Verify that a valid token with 'repo' and 'workflow' scopes passes validation."""
    mock_user = MagicMock()
    mock_user.login = "octocat"
    
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh.oauth_scopes = ["repo", "workflow", "read:user"]
    mock_github_cls.return_value = mock_gh

    res = validate_github_token(token="ghp_validtoken1234567890abcdef")
    assert res["valid"] is True
    assert res["username"] == "octocat"
    assert "repo" in res["scopes"]
    assert "workflow" in res["scopes"]


@patch("github_push.Github")
def test_github_token_from_settings_mocked(mock_github_cls) -> None:
    """Verify that validate_github_token uses token from settings when token is None."""
    mock_user = MagicMock()
    mock_user.login = "settings_user"
    mock_gh = MagicMock()
    mock_gh.get_user.return_value = mock_user
    mock_gh.oauth_scopes = ["repo", "workflow"]
    mock_github_cls.return_value = mock_gh

    with patch("github_push.get_settings") as mock_settings:
        mock_settings.return_value.github_token = "ghp_settingstoken1234567890abcdef"
        res = validate_github_token(token=None)
        assert res["valid"] is True
        assert res["username"] == "settings_user"
