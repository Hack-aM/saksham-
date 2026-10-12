"""Saksham Authentication Module.

Handles user registration, password hashing (bcrypt), session tokens (itsdangerous),
GitHub OAuth flows, and FastAPI request authentication dependencies.
"""

import re
import urllib.parse
from typing import Any, Dict, Optional

import bcrypt
import httpx
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import db
from config import get_settings

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email_format(email: str) -> bool:
    """Validate that an email string meets basic RFC format standards."""
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with a secure salt.

    Args:
        password: Plaintext password string.

    Returns:
        Decoded UTF-8 bcrypt password hash string.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed_bytes = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Args:
        plain_password: User-provided plaintext password.
        hashed_password: Stored bcrypt hash string.

    Returns:
        True if password matches, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def get_serializer(secret_key: Optional[str] = None) -> URLSafeTimedSerializer:
    """Create a URLSafeTimedSerializer instance using the configured session secret."""
    key = secret_key or get_settings().session_secret
    return URLSafeTimedSerializer(secret_key=key, salt="saksham-auth-session")


def create_session_token(user_id: str, secret_key: Optional[str] = None) -> str:
    """Generate a signed, timed session token for a given user ID."""
    serializer = get_serializer(secret_key)
    return serializer.dumps({"user_id": user_id})


def verify_session_token(
    token: str,
    secret_key: Optional[str] = None,
    max_age_seconds: Optional[int] = None,
) -> Optional[str]:
    """Verify and decode a signed session token.

    Args:
        token: The signed session token string.
        secret_key: Optional secret override (uses Settings by default).
        max_age_seconds: Maximum allowed age in seconds.

    Returns:
        The extracted user_id, or None if token is invalid or expired.
    """
    if not token:
        return None
    cfg = get_settings()
    max_age = max_age_seconds if max_age_seconds is not None else cfg.session_max_age_seconds
    serializer = get_serializer(secret_key)
    try:
        data = serializer.loads(token, max_age=max_age)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def register_user(
    email: str,
    password: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Register a new user with email and password.

    Args:
        email: User email address.
        password: Plaintext password (hashed with bcrypt).
        db_path: Optional database path override.

    Returns:
        Safe public user dict if created, None if email already exists or invalid.
    """
    clean_email = email.strip().lower()
    if not validate_email_format(clean_email):
        raise ValueError("Invalid email format.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    pwd_hash = hash_password(password)
    created = db.create_user(
        email=clean_email,
        password_hash=pwd_hash,
        db_path=db_path,
    )
    return created


def authenticate_user(
    email: str,
    password: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Authenticate a user using email and password.

    Args:
        email: User email address.
        password: User plaintext password.
        db_path: Optional database path override.

    Returns:
        Safe public user dict if valid, None if credentials do not match.
    """
    clean_email = email.strip().lower()
    user_row = db.get_user_by_email(clean_email, db_path=db_path)
    if not user_row:
        return None

    stored_hash = user_row.get("password_hash")
    if not stored_hash or not verify_password(password, stored_hash):
        return None

    # Never expose password_hash
    return {
        "id": user_row["id"],
        "email": user_row["email"],
        "github_login": user_row.get("github_login"),
        "created_at": user_row["created_at"],
    }


def get_user_from_token(
    token: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up an authenticated user from a signed session token."""
    user_id = verify_session_token(token)
    if not user_id:
        return None
    user_row = db.get_user_by_id(user_id, db_path=db_path)
    if not user_row:
        return None
    return {
        "id": user_row["id"],
        "email": user_row["email"],
        "github_login": user_row.get("github_login"),
        "created_at": user_row["created_at"],
    }


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract session token from either Authorization header or HTTP-only session cookie."""
    # 1. Bearer token in Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
        if bearer_token:
            return bearer_token

    # 2. HTTP-only session cookie
    cfg = get_settings()
    cookie_token = request.cookies.get(cfg.session_cookie_name)
    if cookie_token:
        return cookie_token

    return None


async def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """Optional FastAPI dependency to resolve current authenticated user."""
    token = extract_token_from_request(request)
    if not token:
        return None
    return get_user_from_token(token)


async def get_current_user_required(request: Request) -> Dict[str, Any]:
    """Required FastAPI dependency that raises HTTP 401 if not authenticated."""
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in.",
        )
    return user


# ── GitHub OAuth ─────────────────────────────────────────────────────────────

def build_github_oauth_url(
    client_id: str,
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
) -> str:
    """Build the GitHub OAuth authorization URL."""
    params = {
        "client_id": client_id,
        "scope": "read:user user:email",
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    if state:
        params["state"] = state
    query = urllib.parse.urlencode(params)
    return f"https://github.com/login/oauth/authorize?{query}"


async def exchange_github_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: Optional[str] = None,
) -> Optional[str]:
    """Exchange temporary OAuth authorization code for a GitHub access token."""
    payload: Dict[str, str] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri

    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data=payload,
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("access_token")


async def fetch_github_user_info(access_token: str) -> Optional[Dict[str, Any]]:
    """Fetch profile data and primary verified email from GitHub API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Saksham-App",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Fetch user profile
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        if user_resp.status_code != 200:
            return None
        user_data = user_resp.json()
        github_id = str(user_data.get("id"))
        github_login = user_data.get("login") or f"user_{github_id}"
        email = user_data.get("email")

        # 2. If email is not public, fetch user emails list
        if not email:
            emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
            if emails_resp.status_code == 200:
                emails_list = emails_resp.json()
                # Find primary verified email first
                for em in emails_list:
                    if em.get("primary") and em.get("verified"):
                        email = em.get("email")
                        break
                # Fallback to any verified email
                if not email:
                    for em in emails_list:
                        if em.get("verified"):
                            email = em.get("email")
                            break

        # Fallback to synthetic github email if user has no visible email
        if not email:
            email = f"{github_login}@users.noreply.github.com"

        return {
            "github_id": github_id,
            "github_login": github_login,
            "email": email,
        }
