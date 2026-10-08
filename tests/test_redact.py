"""Unit tests for secret redaction in redact.py."""

from redact import redact_text


def test_redact_generic_key_assignment() -> None:
    """Verify generic KEY assignments mask the sensitive string."""
    input_text = 'SOME_KEY = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"'
    redacted = redact_text(input_text)
    assert 'SOME_KEY = "[REDACTED]"' in redacted
    assert "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0" not in redacted


def test_redact_authorization_bearer_token() -> None:
    """Verify Authorization: Bearer <token> masks the token string."""
    input_text = "curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret_payload' http://api.com"
    redacted = redact_text(input_text)
    assert "Authorization: Bearer [REDACTED]" in redacted
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret_payload" not in redacted


def test_redact_standard_prefixed_keys() -> None:
    """Verify OpenAI, GitHub, and Render style tokens are masked."""
    text = (
        "Leaked keys: sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI, "
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz, and "
        "rnd_abcdefghijklmnopqrstuvwxyz123456"
    )
    redacted = redact_text(text)
    assert "sk-proj-9x7KqLm2PvR8wT4yB1nC3eF6gH0jM5zX8uI" not in redacted
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "rnd_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_redact_custom_secrets() -> None:
    """Verify explicitly provided secrets are masked."""
    text = "Connecting to database with custom_db_password_9999"
    redacted = redact_text(text, custom_secrets=["custom_db_password_9999"])
    assert "custom_db_password_9999" not in redacted
    assert "Connecting to database with [REDACTED]" in redacted


def test_redact_empty_or_clean_text() -> None:
    """Verify clean text and empty inputs pass through unchanged."""
    assert redact_text("") == ""
    assert redact_text("Hello World, clean FastAPI code!") == "Hello World, clean FastAPI code!"
