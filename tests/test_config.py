"""Unit tests for configuration loading and validation in config.py."""

import pytest
from config import Settings, ConfigurationError, get_settings


def test_default_settings() -> None:
    """Verify default values when optional settings are omitted."""
    settings = Settings(
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-2.5-flash",
        github_token="test-gh-token",
        render_api_key="test-render-key",
    )
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.port == 8000
    assert settings.environment == "development"
    assert settings.max_upload_size_bytes == 25 * 1024 * 1024
    assert settings.db_path.endswith("saksham.db")


def test_custom_settings() -> None:
    """Verify that custom values properly override defaults."""
    settings = Settings(
        gemini_api_key="custom-gemini",
        gemini_model="gemini-1.5-pro",
        github_token="custom-gh",
        render_api_key="custom-render",
        port=9000,
        environment="production",
        db_path="/tmp/custom.db",
        max_upload_size_bytes=10 * 1024 * 1024,
    )
    assert settings.gemini_api_key == "custom-gemini"
    assert settings.gemini_model == "gemini-1.5-pro"
    assert settings.github_token == "custom-gh"
    assert settings.render_api_key == "custom-render"
    assert settings.port == 9000
    assert settings.environment == "production"
    assert settings.db_path == "/tmp/custom.db"
    assert settings.max_upload_size_bytes == 10 * 1024 * 1024


def test_validation_success() -> None:
    """Verify that validate_required_keys passes when all mandatory keys are provided."""
    settings = Settings(
        gemini_api_key="valid-gemini-key",
        gemini_model="gemini-2.5-flash",
        github_token="valid-github-token",
        render_api_key="valid-render-key",
    )
    # Should not raise any error
    settings.validate_required_keys()


def test_validation_failure_missing_all() -> None:
    """Verify that validate_required_keys raises ConfigurationError if keys are missing."""
    settings = Settings(
        gemini_api_key="",
        gemini_model="",
        github_token="",
        render_api_key="",
    )
    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_required_keys()
    
    msg = str(exc_info.value)
    assert "Missing required environment variables" in msg
    assert "GEMINI_API_KEY" in msg
    assert "GEMINI_MODEL" in msg
    assert "GITHUB_TOKEN" in msg
    assert "RENDER_API_KEY" in msg


def test_validation_failure_missing_single() -> None:
    """Verify that validate_required_keys specifies the exact missing key."""
    settings = Settings(
        gemini_api_key="valid-key",
        gemini_model="gemini-2.5-flash",
        github_token="valid-token",
        render_api_key="",
    )
    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_required_keys()

    msg = str(exc_info.value)
    assert "RENDER_API_KEY" in msg
    assert "GEMINI_API_KEY" not in msg
    assert "GEMINI_MODEL" not in msg
    assert "GITHUB_TOKEN" not in msg


def test_get_settings_singleton() -> None:
    """Verify that get_settings returns a valid Settings instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


# ---------------------------------------------------------------------------
# PORT environment-variable regression tests (T31 security review)
# Each test patches os.getenv directly to isolate from the real .env file.
# ---------------------------------------------------------------------------

def test_port_unset_uses_default() -> None:
    """PORT absent from environment must resolve to the default 8000."""
    import os
    from unittest.mock import patch

    env_without_port = {k: v for k, v in os.environ.items() if k != "PORT"}
    with patch.dict(os.environ, env_without_port, clear=True):
        settings = Settings()
        assert settings.port == 8000


def test_port_empty_string_uses_default() -> None:
    """PORT='' (blank line in .env) must resolve to the default 8000, not raise."""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"PORT": ""}, clear=False):
        settings = Settings()
        assert settings.port == 8000


def test_port_valid_value_is_preserved() -> None:
    """PORT=9000 must resolve to 9000, not the default."""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"PORT": "9000"}, clear=False):
        settings = Settings()
        assert settings.port == 9000
