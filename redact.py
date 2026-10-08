"""Saksham Secret Redaction Module.

Provides helpers to mask sensitive API keys, tokens, credentials, and secrets
before storing data in SQLite database tables or streaming logs.
"""

import re
from typing import List, Optional

# Regex patterns matching known secret formats and assignments
SECRET_PATTERNS = [
    # 1. Authorization: Bearer <token> or Bearer <token>
    (re.compile(r"(Authorization:\s*Bearer\s+)[^\s\r\n\'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE), r"\1[REDACTED]"),

    # 2. Key assignments: VAR_KEY = "..." or some_secret = '...' (values >= 16 chars)
    (
        re.compile(
            r"""([A-Za-z0-9_]*(?:KEY|SECRET|TOKEN|PASS|PASSWORD|AUTH|CREDENTIAL|PRIVATE)[A-Za-z0-9_]*\s*=\s*['"])[^'"]{16,}(['"])""",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]\2",
    ),

    # 3. Known specific token prefixes
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), "[REDACTED]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{70,}"), "[REDACTED]"),
    (re.compile(r"gho_[a-zA-Z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"ghu_[a-zA-Z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"ghs_[a-zA-Z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"ghr_[a-zA-Z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"rnd_[a-zA-Z0-9]{24,}"), "[REDACTED]"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "[REDACTED]"),
]


def redact_text(text: str, custom_secrets: Optional[List[str]] = None) -> str:
    """Mask known secrets and custom secret values from text strings.

    Args:
        text: The input text that may contain sensitive data.
        custom_secrets: Optional list of explicit secret strings to redact.

    Returns:
        str: Redacted text with secrets replaced by '[REDACTED]'.
    """
    if not text:
        return text

    redacted = text

    # Redact explicitly provided secret strings
    if custom_secrets:
        for secret in custom_secrets:
            if secret and len(secret) > 3:
                redacted = redacted.replace(secret, "[REDACTED]")

    # Redact using standard pattern matching
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)

    return redacted
