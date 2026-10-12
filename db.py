"""Saksham SQLite Persistence Module.

Handles database initialization, schema creation, and parameterized CRUD operations
for analysis runs, issues, patches, and deployment history per ARCHITECTURE.md section 4.
Security: No tokens or secret values are stored in the database.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from config import get_settings
from redact import redact_text


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database file path from parameter or application settings."""
    if custom_path:
        return custom_path
    return get_settings().db_path


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and return a configured sqlite3 connection with Row factory."""
    resolved_path = get_db_path(db_path)
    # Ensure parent directory exists
    Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database tables if they do not exist."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # 1. Analysis table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                stack TEXT NOT NULL,
                score INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        # 2. Issues table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                file TEXT NOT NULL,
                line INTEGER NOT NULL,
                explanation TEXT NOT NULL,
                FOREIGN KEY (analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
            );
        """)

        # 3. Patches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patches (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                issue_id TEXT,
                file TEXT NOT NULL,
                old_content TEXT NOT NULL,
                new_content TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'suggested',
                FOREIGN KEY (analysis_id) REFERENCES analyses (id) ON DELETE CASCADE,
                FOREIGN KEY (issue_id) REFERENCES issues (id) ON DELETE SET NULL
            );
        """)

        # 4. Deployments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deployments (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                repo_url TEXT NOT NULL,
                live_url TEXT NOT NULL,
                platform TEXT NOT NULL,
                health_status TEXT NOT NULL,
                final_score INTEGER NOT NULL,
                logs TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
            );
        """)

        # 5. Users table (T36 authentication)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                github_id TEXT UNIQUE,
                github_login TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.commit()


def save_analysis(
    project_name: str,
    stack: str,
    score: int,
    issues: List[Dict[str, Any]],
    patches: List[Dict[str, Any]],
    analysis_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Save an analysis run with its associated issues and proposed patches.
    Sensitive tokens and secret patterns are automatically redacted before insertion.

    Args:
        project_name: Name of the project analyzed.
        stack: Detected stack description or JSON string.
        score: Initial Deploy Readiness Score (0-100).
        issues: List of detected issues.
        patches: List of proposed patches.
        analysis_id: Optional explicit analysis ID (defaults to new UUID).
        db_path: Optional custom database path.

    Returns:
        str: Unique analysis ID.
    """
    effective_id = analysis_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO analyses (id, project_name, stack, score, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (effective_id, project_name, stack, score, created_at),
        )

        for issue in issues:
            issue_id = issue.get("id") or str(uuid.uuid4())
            sanitized_title = redact_text(issue.get("title", ""))
            sanitized_explanation = redact_text(issue.get("explanation", ""))
            cursor.execute(
                """
                INSERT INTO issues (id, analysis_id, severity, title, file, line, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    effective_id,
                    issue.get("severity", "Medium"),
                    sanitized_title,
                    issue.get("file", ""),
                    int(issue.get("line", 0)),
                    sanitized_explanation,
                ),
            )

        for patch in patches:
            patch_id = patch.get("id") or str(uuid.uuid4())
            sanitized_old = redact_text(patch.get("old", ""))
            sanitized_new = redact_text(patch.get("new", ""))
            sanitized_reason = redact_text(patch.get("reason", ""))
            cursor.execute(
                """
                INSERT INTO patches (id, analysis_id, issue_id, file, old_content, new_content, reason, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patch_id,
                    effective_id,
                    patch.get("issue_id"),
                    patch.get("file", ""),
                    sanitized_old,
                    sanitized_new,
                    sanitized_reason,
                    patch.get("status", "suggested"),
                ),
            )

        conn.commit()

    return effective_id


def get_analysis(analysis_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve an analysis by ID including its issues and patches."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,))
        row = cursor.fetchone()
        if not row:
            return None

        analysis = dict(row)

        cursor.execute("SELECT * FROM issues WHERE analysis_id = ?", (analysis_id,))
        analysis["issues"] = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM patches WHERE analysis_id = ?", (analysis_id,))
        analysis["patches"] = [dict(r) for r in cursor.fetchall()]

        return analysis


def list_analyses(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List recent analysis records."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]


def save_deployment(
    analysis_id: str,
    repo_url: str,
    live_url: str,
    platform: str,
    health_status: str,
    final_score: int,
    logs: str,
    db_path: Optional[str] = None,
) -> str:
    """Record a deployment run associated with an analysis, redacting any sensitive logs."""
    deployment_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    sanitized_logs = redact_text(logs)

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO deployments (id, analysis_id, repo_url, live_url, platform, health_status, final_score, logs, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deployment_id,
                analysis_id,
                repo_url,
                live_url,
                platform,
                health_status,
                final_score,
                sanitized_logs,
                created_at,
            ),
        )
        conn.commit()

    return deployment_id


def get_deployment(deployment_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a single deployment record by ID."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_deployments(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List recent deployments ordered by creation timestamp."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.*, a.project_name, a.score as initial_score
            FROM deployments d
            JOIN analyses a ON d.analysis_id = a.id
            ORDER BY d.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cursor.fetchall()]


def update_patch_status(patch_id: str, status: str, db_path: Optional[str] = None) -> bool:
    """Update the status of a patch (e.g. 'suggested', 'approved', 'applied')."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE patches SET status = ? WHERE id = ?", (status, patch_id))
        conn.commit()
        return cursor.rowcount > 0


# ── T36: User CRUD helpers ─────────────────────────────────────────────────

def create_user(
    email: str,
    password_hash: Optional[str] = None,
    github_id: Optional[str] = None,
    github_login: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Insert a new user row.

    Returns:
        The created user dict, or None if the email is already taken.
    """
    user_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (id, email, password_hash, github_id, github_login, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, email.lower().strip(), password_hash, github_id, github_login, created_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # UNIQUE constraint on email or github_id
            return None
    return {
        "id": user_id,
        "email": email.lower().strip(),
        "github_login": github_login,
        "created_at": created_at,
    }


def get_user_by_email(email: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a user row by email (lowercased for comparison)."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, password_hash, github_id, github_login, created_at FROM users WHERE email = ?",
            (email.lower().strip(),),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_github_id(github_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a user row by GitHub numeric user ID."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, password_hash, github_id, github_login, created_at FROM users WHERE github_id = ?",
            (github_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def upsert_github_user(
    github_id: str,
    github_login: str,
    email: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a user from GitHub OAuth data.

    If a user already exists with this github_id or email, update their GitHub
    metadata and return the existing row.  Otherwise create a new one.

    Returns:
        The user dict (never contains password_hash).
    """
    normalised_email = email.lower().strip()
    # Check by github_id first, then by email
    existing = get_user_by_github_id(github_id, db_path)
    if not existing:
        existing = get_user_by_email(normalised_email, db_path)

    if existing:
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE users SET github_id = ?, github_login = ? WHERE id = ?",
                (github_id, github_login, existing["id"]),
            )
            conn.commit()
        return {
            "id": existing["id"],
            "email": existing["email"],
            "github_login": github_login,
            "created_at": existing["created_at"],
        }

    # New user from GitHub
    created = create_user(
        email=normalised_email,
        github_id=github_id,
        github_login=github_login,
        db_path=db_path,
    )
    if created is None:
        # Race condition: second lookup after concurrent insert
        row = get_user_by_email(normalised_email, db_path) or {}
        return {
            "id": row.get("id", ""),
            "email": normalised_email,
            "github_login": github_login,
            "created_at": row.get("created_at", ""),
        }
    return created


def get_user_by_id(user_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a user row by user UUID."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, password_hash, github_id, github_login, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
