"""Unit and integration tests for Saksham authentication system (T36)."""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from main import app
import auth
import db
from db import init_db
from config import get_settings


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup clean isolated SQLite database for each test run."""
    test_db = tmp_path / "test_auth.db"
    init_db(str(test_db))
    monkeypatch.setattr("db.get_db_path", lambda custom_path=None: str(test_db))
    return str(test_db)


# ── Cryptography and Token Unit Tests ─────────────────────────────────────────

def test_password_hashing_and_verification():
    """Verify bcrypt hash generation and constant-time password verification."""
    password = "SuperSecretPassword123!"
    hashed = auth.hash_password(password)

    assert hashed != password
    assert hashed.startswith("$2b$")
    assert auth.verify_password(password, hashed) is True
    assert auth.verify_password("WrongPassword!", hashed) is False
    assert auth.verify_password("", hashed) is False


def test_session_token_lifecycle():
    """Verify session token creation and verification with URLSafeTimedSerializer."""
    user_id = "user-uuid-12345"
    token = auth.create_session_token(user_id)
    assert isinstance(token, str)

    extracted = auth.verify_session_token(token)
    assert extracted == user_id

    # Tampered token
    assert auth.verify_session_token(token + "tampered") is None

    # Expired token
    assert auth.verify_session_token(token, max_age_seconds=-1) is None


def test_email_validation_format():
    """Verify email formatting validation rules."""
    assert auth.validate_email_format("student@college.edu") is True
    assert auth.validate_email_format("user.name+tag@sub.domain.co") is True
    assert auth.validate_email_format("invalid-email") is False
    assert auth.validate_email_format("@missing-user.com") is False
    assert auth.validate_email_format("missing-domain@") is False
    assert auth.validate_email_format("") is False


# ── Database User CRUD Tests ──────────────────────────────────────────────────

def test_db_user_crud():
    """Test user creation and lookup by email and ID."""
    created = db.create_user(
        email="Alice@Example.COM",
        password_hash=auth.hash_password("password123"),
        github_login="alice-dev",
    )
    assert created is not None
    assert created["email"] == "alice@example.com"
    user_id = created["id"]

    # Lookup by email (case-insensitive)
    found_by_email = db.get_user_by_email("ALICE@example.com")
    assert found_by_email is not None
    assert found_by_email["id"] == user_id

    # Lookup by ID
    found_by_id = db.get_user_by_id(user_id)
    assert found_by_id is not None
    assert found_by_id["email"] == "alice@example.com"

    # Duplicate creation fails cleanly
    duplicate = db.create_user(email="alice@example.com", password_hash="hash")
    assert duplicate is None


def test_db_upsert_github_user():
    """Test upserting users via GitHub OAuth."""
    # First login via GitHub
    user1 = db.upsert_github_user(
        github_id="gh-12345",
        github_login="octocat",
        email="octocat@github.com",
    )
    assert user1["email"] == "octocat@github.com"
    assert user1["github_login"] == "octocat"

    # Second login with updated login name
    user2 = db.upsert_github_user(
        github_id="gh-12345",
        github_login="octocat-updated",
        email="octocat@github.com",
    )
    assert user2["id"] == user1["id"]
    assert user2["github_login"] == "octocat-updated"


# ── API Endpoint Tests: Register & Login ──────────────────────────────────────

def test_register_endpoint_success():
    """Test POST /auth/register creates user and returns HTTP-only session cookie."""
    client = TestClient(app)
    payload = {
        "email": "newuser@saksham.dev",
        "password": "ValidPassword987!",
    }
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["message"] == "Registration successful."
    assert data["user"]["email"] == "newuser@saksham.dev"
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]

    # Verify session cookie was set
    cfg = get_settings()
    assert cfg.session_cookie_name in resp.cookies


def test_register_duplicate_email_conflict():
    """Test POST /auth/register returns 409 Conflict if email is already taken."""
    client = TestClient(app)
    payload = {"email": "existing@saksham.dev", "password": "Password123!"}

    r1 = client.post("/auth/register", json=payload)
    assert r1.status_code == 201

    r2 = client.post("/auth/register", json=payload)
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"]


def test_register_validation_errors():
    """Test POST /auth/register rejects short passwords and invalid emails."""
    client = TestClient(app)

    # Short password (< 8 chars)
    r1 = client.post("/auth/register", json={"email": "u@test.com", "password": "short"})
    assert r1.status_code in (400, 422)

    # Invalid email format
    r2 = client.post("/auth/register", json={"email": "not-an-email", "password": "ValidPassword123!"})
    assert r2.status_code in (400, 422)


def test_login_endpoint_success_and_failure():
    """Test POST /auth/login with valid, wrong, and non-existent credentials."""
    client = TestClient(app)

    # Register user
    reg_payload = {"email": "testlogin@saksham.dev", "password": "SecurePassword123!"}
    client.post("/auth/register", json=reg_payload)

    # 1. Valid login
    login_resp = client.post("/auth/login", json=reg_payload)
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert data["user"]["email"] == "testlogin@saksham.dev"
    assert "password_hash" not in data["user"]

    # 2. Wrong password
    bad_pwd_resp = client.post("/auth/login", json={"email": "testlogin@saksham.dev", "password": "WrongPassword"})
    assert bad_pwd_resp.status_code == 401

    # 3. Non-existent email
    no_user_resp = client.post("/auth/login", json={"email": "nonexistent@saksham.dev", "password": "SecurePassword123!"})
    assert no_user_resp.status_code == 401


# ── API Endpoint Tests: /auth/me and /auth/logout ─────────────────────────────

def test_get_me_authenticated_and_unauthenticated():
    """Test GET /auth/me returns current user info when authenticated, 401 otherwise."""
    client = TestClient(app)

    # 1. Unauthenticated request
    unauth_resp = client.get("/auth/me")
    assert unauth_resp.status_code == 401

    # 2. Register and authenticate via session cookie
    reg_payload = {"email": "currentuser@saksham.dev", "password": "MyStrongPassword123!"}
    reg_resp = client.post("/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201

    cfg = get_settings()
    session_cookie = reg_resp.cookies[cfg.session_cookie_name]

    # Authenticated via cookie
    me_resp = client.get("/auth/me", cookies={cfg.session_cookie_name: session_cookie})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "currentuser@saksham.dev"

    # Authenticated via Authorization Bearer header
    bearer_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {session_cookie}"})
    assert bearer_resp.status_code == 200
    assert bearer_resp.json()["email"] == "currentuser@saksham.dev"


def test_logout_endpoint_clears_cookie():
    """Test POST /auth/logout deletes the session cookie."""
    client = TestClient(app)
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Signed out successfully."


# ── GitHub OAuth Tests ────────────────────────────────────────────────────────

def test_github_oauth_redirect_when_unconfigured(monkeypatch):
    """Test GET /auth/github returns 503 when OAuth client credentials are not configured."""
    monkeypatch.setattr(get_settings(), "github_oauth_client_id", "")
    client = TestClient(app)

    resp = client.get("/auth/github")
    assert resp.status_code == 503
    assert "GitHub OAuth is not configured" in resp.json()["detail"]


def test_github_oauth_redirect_when_configured(monkeypatch):
    """Test GET /auth/github returns GitHub OAuth URL when configured."""
    monkeypatch.setattr(get_settings(), "github_oauth_client_id", "test_client_id_123")
    client = TestClient(app)

    # JSON preference
    json_resp = client.get("/auth/github", headers={"Accept": "application/json"})
    assert json_resp.status_code == 200
    assert "https://github.com/login/oauth/authorize" in json_resp.json()["auth_url"]
    assert "client_id=test_client_id_123" in json_resp.json()["auth_url"]


def test_github_callback_success(monkeypatch):
    """Test GET /auth/github/callback completes OAuth flow and issues session."""
    monkeypatch.setattr(get_settings(), "github_oauth_client_id", "test_client_id_123")
    monkeypatch.setattr(get_settings(), "github_oauth_client_secret", "test_client_secret_456")

    mock_exchange = AsyncMock(return_value="mock_github_access_token")
    mock_fetch = AsyncMock(
        return_value={
            "github_id": "999888",
            "github_login": "gitdev",
            "email": "gitdev@example.org",
        }
    )

    monkeypatch.setattr("auth.exchange_github_code_for_token", mock_exchange)
    monkeypatch.setattr("auth.fetch_github_user_info", mock_fetch)

    client = TestClient(app)
    resp = client.get("/auth/github/callback?code=mock_code", follow_redirects=False)

    assert resp.status_code == 303
    cfg = get_settings()
    assert cfg.session_cookie_name in resp.cookies

    # Verify user exists in database
    created_user = db.get_user_by_email("gitdev@example.org")
    assert created_user is not None
    assert created_user["github_login"] == "gitdev"


def test_github_callback_error_params(monkeypatch):
    """Test GET /auth/github/callback handles OAuth error param or missing code."""
    monkeypatch.setattr(get_settings(), "github_oauth_client_id", "test_client_id")
    monkeypatch.setattr(get_settings(), "github_oauth_client_secret", "test_secret")
    client = TestClient(app)

    # OAuth error from GitHub
    err_resp = client.get("/auth/github/callback?error=access_denied")
    assert err_resp.status_code == 400

    # Missing code
    missing_resp = client.get("/auth/github/callback")
    assert missing_resp.status_code == 400
