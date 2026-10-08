"""Unit tests for Fixer patch proposal generation in fixer.py (T16).

All tests use mocks to ensure no real network or API calls are made to Google Gemini,
and assert that the fixer is completely read-only and enforces strict security.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from config import Settings
from fixer import (
    FixerError,
    InvalidPatchError,
    PatchLLMResponse,
    propose_patch_for_issue,
    propose_patches_for_issues,
    validate_patch_safety,
)
from llm import GeminiLLMClient, LLMResponseError, LLMTimeoutError
from schemas import Issue, Patch, PatchStatusEnum, SeverityEnum

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VULNERABLE_APP_DIR = FIXTURES_DIR / "vulnerable-demo-app"
CLEAN_APP_DIR = FIXTURES_DIR / "clean-app"


@pytest.fixture
def mock_llm_client():
    """Create a mocked GeminiLLMClient."""
    client = MagicMock(spec=GeminiLLMClient)
    return client


def test_path_traversal_rejected_by_validator(tmp_path):
    """Verify that patches referencing .. or traversal are rejected."""
    patch_obj = Patch(
        file="../../etc/passwd",
        old="root",
        new="admin",
        reason="Malicious patch",
    )
    with pytest.raises(InvalidPatchError) as exc_info:
        validate_patch_safety(patch_obj, tmp_path)
    assert "traversal" in str(exc_info.value).lower() or "escapes" in str(exc_info.value).lower()


def test_absolute_path_rejected_by_validator(tmp_path):
    """Verify that patches referencing absolute paths are rejected."""
    patch_obj = Patch(
        file="/var/log/app.log",
        old="old",
        new="new",
        reason="Absolute path patch",
    )
    with pytest.raises(InvalidPatchError) as exc_info:
        validate_patch_safety(patch_obj, tmp_path)
    assert "absolute" in str(exc_info.value).lower()


def test_command_injection_rejected_by_validator(tmp_path):
    """Verify that patches containing dangerous shell execution syntax are rejected."""
    patch_obj = Patch(
        file="config.py",
        old="DEBUG = True",
        new='import os; os.system("rm -rf /")',
        reason="Malicious injection",
    )
    with pytest.raises(InvalidPatchError) as exc_info:
        validate_patch_safety(patch_obj, tmp_path)
    assert "dangerous command execution" in str(exc_info.value).lower()


def test_deterministic_missing_gitignore_patch(tmp_path):
    """Verify deterministic patch generation for missing .env in .gitignore."""
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    issue = Issue(
        id="iss-gitignore",
        severity=SeverityEnum.MEDIUM,
        title="Missing .gitignore entry for .env",
        file=".gitignore",
        line=0,
        explanation=".env is not listed in .gitignore. Secrets could be leaked.",
    )
    patch_res = propose_patch_for_issue(issue, tmp_path)
    assert patch_res is not None
    assert patch_res.file == ".gitignore"
    assert ".env" in patch_res.new
    assert patch_res.status == PatchStatusEnum.SUGGESTED


def test_deterministic_hardcoded_port_patch(tmp_path):
    """Verify deterministic patch generation for hardcoded port in main.py."""
    main_file = tmp_path / "main.py"
    main_file.write_text('uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)', encoding="utf-8")
    issue = Issue(
        id="iss-port",
        severity=SeverityEnum.MEDIUM,
        title="Hardcoded server port: 8000",
        file="main.py",
        line=1,
        explanation="Server port is hardcoded to 8000.",
    )
    patch_res = propose_patch_for_issue(issue, tmp_path)
    assert patch_res is not None
    assert "os.getenv" in patch_res.new
    assert "PORT" in patch_res.new


def test_deterministic_secret_leak_patch_never_invents_credentials(tmp_path):
    """Verify hardcoded secret is moved to os.getenv and no invented fake credentials are generated."""
    config_file = tmp_path / "config.py"
    secret_val = "v8K9#mX2$pL5!jN8@qR4*wT7^yB1&cE3"
    config_file.write_text(f'API_KEY = "{secret_val}"\n', encoding="utf-8")

    issue = Issue(
        id="iss-secret",
        severity=SeverityEnum.HIGH,
        title="Hardcoded secret detected",
        file="config.py",
        line=1,
        explanation=f"Found hardcoded API key {secret_val}",
    )
    patch_res = propose_patch_for_issue(issue, tmp_path)
    assert patch_res is not None
    assert patch_res.new.strip() == 'API_KEY = os.getenv("API_KEY", "")'
    # Ensure replacement does NOT generate an invented secret
    assert secret_val not in patch_res.new


def test_llm_fix_proposal_sanitizes_context(tmp_path, mock_llm_client):
    """Verify that when calling LLM, prompt context has secrets redacted."""
    target_file = tmp_path / "custom.py"
    secret_key = "AIzaSyFakeSecretKey1234567890abcdefghij"
    target_file.write_text(f'def get_headers():\n    return {{"Authorization": "Bearer {secret_key}"}}\n', encoding="utf-8")

    issue = Issue(
        id="iss-custom",
        severity=SeverityEnum.HIGH,
        title="Insecure custom header authorization",
        file="custom.py",
        line=2,
        explanation=f"Exposed authorization token in headers: {secret_key}",
    )

    mock_llm_client.generate_structured.return_value = PatchLLMResponse(
        file="custom.py",
        old=f'"Authorization": "Bearer {secret_key}"',
        new='"Authorization": f"Bearer {os.getenv(\'API_TOKEN\', \'\')}"',
        reason="Move authorization token to environment variable",
    )

    patch_res = propose_patch_for_issue(issue, tmp_path, llm_client=mock_llm_client)
    assert patch_res is not None
    assert patch_res.file == "custom.py"

    # Verify prompt passed to generate_structured does NOT contain raw secret
    assert mock_llm_client.generate_structured.called
    called_prompt = mock_llm_client.generate_structured.call_args.kwargs["prompt"]
    assert secret_key not in called_prompt
    assert "[REDACTED]" in called_prompt



def test_llm_malformed_response_handled_safely(tmp_path, mock_llm_client):
    """Verify that an LLM response error fails safely without crashing pipeline."""
    target_file = tmp_path / "app.py"
    target_file.write_text('def run(): pass\n', encoding="utf-8")

    issue = Issue(
        id="iss-1",
        severity=SeverityEnum.LOW,
        title="Custom issue",
        file="app.py",
        line=1,
        explanation="Custom issue description",
    )

    mock_llm_client.generate_structured.side_effect = LLMResponseError("Invalid JSON schema")
    patch_res = propose_patch_for_issue(issue, tmp_path, llm_client=mock_llm_client)
    assert patch_res is None


def test_propose_patches_for_vulnerable_fixture_produces_3_patches():
    """Verify that running fixer on vulnerable-demo-app produces exactly 3 valid proposals."""
    issues = [
        Issue(
            id="iss-1",
            severity=SeverityEnum.HIGH,
            title="Hardcoded secret detected",
            file="config.py",
            line=12,
            explanation="API_KEY found on line 12",
        ),
        Issue(
            id="iss-2",
            severity=SeverityEnum.MEDIUM,
            title="Missing .gitignore entry for .env",
            file=".gitignore",
            line=0,
            explanation=".env is not listed in .gitignore.",
        ),
        Issue(
            id="iss-3",
            severity=SeverityEnum.MEDIUM,
            title="Hardcoded server port",
            file="main.py",
            line=14,
            explanation="Hardcoded port 8000 in uvicorn.run",
        ),
    ]

    patches = propose_patches_for_issues(issues, VULNERABLE_APP_DIR)
    assert len(patches) == 3
    for p in patches:
        assert p.status == PatchStatusEnum.SUGGESTED
        assert len(p.old) > 0
        assert len(p.new) > 0
        assert len(p.reason) > 0


def test_fixer_is_read_only_and_does_not_modify_files(tmp_path):
    """Verify that running fixer does NOT alter file contents on disk."""
    config_file = tmp_path / "config.py"
    original_content = 'API_KEY = "v8K9#mX2$pL5!jN8@qR4*wT7^yB1&cE3"\n'
    config_file.write_text(original_content, encoding="utf-8")

    issue = Issue(
        id="iss-read-only",
        severity=SeverityEnum.HIGH,
        title="Hardcoded secret",
        file="config.py",
        line=1,
        explanation="Secret found",
    )

    patches = propose_patches_for_issues([issue], tmp_path)
    assert len(patches) == 1

    # Assert disk file content is 100% UNCHANGED
    current_content = config_file.read_text(encoding="utf-8")
    assert current_content == original_content


def test_empty_or_clean_issues_returns_empty_patches(tmp_path):
    """Verify that an empty issues list returns an empty patches list."""
    patches = propose_patches_for_issues([], tmp_path)
    assert patches == []
