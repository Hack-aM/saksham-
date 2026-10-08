"""Unit tests for Patch application and Unified Diff generation in fixer.py (T17)."""

import os
from pathlib import Path
import pytest

from fixer import (
    InvalidPatchError,
    PatchApplicationError,
    PatchMatchError,
    UnapprovedPatchError,
    apply_patch,
    apply_patches,
    generate_patch_diff,
    generate_unified_diff,
)
from schemas import Patch, PatchStatusEnum


def test_approved_patch_applies_successfully(tmp_path):
    """Verify that an approved patch applies cleanly to an existing file."""
    test_file = tmp_path / "config.py"
    test_file.write_text('API_KEY = "v8K9#mX2$pL5!jN8@qR4*wT7^yB1&cE3"\n', encoding="utf-8")

    patch_obj = Patch(
        file="config.py",
        old='API_KEY = "v8K9#mX2$pL5!jN8@qR4*wT7^yB1&cE3"',
        new='API_KEY = os.getenv("API_KEY", "")',
        reason="Move key to environment variable",
        status=PatchStatusEnum.APPROVED,
    )

    applied_patch = apply_patch(patch_obj, tmp_path)
    assert applied_patch.status == PatchStatusEnum.APPLIED
    assert test_file.read_text(encoding="utf-8") == 'API_KEY = os.getenv("API_KEY", "")\n'


def test_suggested_patch_is_rejected_without_modifying_file(tmp_path):
    """Verify that an unapproved (suggested) patch is rejected with UnapprovedPatchError."""
    test_file = tmp_path / "config.py"
    original = 'DEBUG = True\n'
    test_file.write_text(original, encoding="utf-8")

    patch_obj = Patch(
        file="config.py",
        old="DEBUG = True",
        new="DEBUG = False",
        reason="Disable debug",
        status=PatchStatusEnum.SUGGESTED,  # Not approved!
    )

    with pytest.raises(UnapprovedPatchError) as exc_info:
        apply_patch(patch_obj, tmp_path)
    assert "must be explicitly APPROVED" in str(exc_info.value)
    assert test_file.read_text(encoding="utf-8") == original


def test_exact_old_content_mismatch_is_rejected(tmp_path):
    """Verify that a patch fails safely with PatchMatchError if old content does not match."""
    test_file = tmp_path / "main.py"
    original = 'port = 9000\n'
    test_file.write_text(original, encoding="utf-8")

    patch_obj = Patch(
        file="main.py",
        old="port = 8000",  # Does not match 'port = 9000'
        new='port = int(os.getenv("PORT", "8000"))',
        reason="Update port",
        status=PatchStatusEnum.APPROVED,
    )

    with pytest.raises(PatchMatchError) as exc_info:
        apply_patch(patch_obj, tmp_path)
    assert "not found in target file" in str(exc_info.value)
    assert test_file.read_text(encoding="utf-8") == original


def test_path_traversal_rejected_on_apply(tmp_path):
    """Verify that path traversal in patch.file is rejected on apply."""
    patch_obj = Patch(
        file="../evil.py",
        old="",
        new="malicious = True",
        reason="Escape",
        status=PatchStatusEnum.APPROVED,
    )
    with pytest.raises(InvalidPatchError):
        apply_patch(patch_obj, tmp_path)


def test_absolute_path_rejected_on_apply(tmp_path):
    """Verify that absolute paths in patch.file are rejected on apply."""
    patch_obj = Patch(
        file="/etc/hosts",
        old="",
        new="127.0.0.1 fake",
        reason="Escape",
        status=PatchStatusEnum.APPROVED,
    )
    with pytest.raises(InvalidPatchError):
        apply_patch(patch_obj, tmp_path)


def test_windows_drive_path_rejected_on_apply(tmp_path):
    """Verify that Windows drive paths in patch.file are rejected on apply."""
    patch_obj = Patch(
        file="C:evil.py",
        old="",
        new="malicious = True",
        reason="Escape",
        status=PatchStatusEnum.APPROVED,
    )
    with pytest.raises(InvalidPatchError):
        apply_patch(patch_obj, tmp_path)


def test_directory_target_rejected_on_apply(tmp_path):
    """Verify that attempting to patch a directory raises InvalidPatchError."""
    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()

    patch_obj = Patch(
        file="subdir",
        old="old",
        new="new",
        reason="Invalid target",
        status=PatchStatusEnum.APPROVED,
    )
    with pytest.raises(InvalidPatchError) as exc_info:
        apply_patch(patch_obj, tmp_path)
    assert "directory" in str(exc_info.value).lower()


def test_new_file_creation_patch_applies_successfully(tmp_path):
    """Verify that a patch creating a new file (old='') works cleanly."""
    new_file = tmp_path / ".gitignore"
    assert not new_file.exists()

    patch_obj = Patch(
        file=".gitignore",
        old="",
        new=".env\n__pycache__/\n",
        reason="Create gitignore",
        status=PatchStatusEnum.APPROVED,
    )

    applied = apply_patch(patch_obj, tmp_path)
    assert applied.status == PatchStatusEnum.APPLIED
    assert new_file.is_file()
    assert new_file.read_text(encoding="utf-8") == ".env\n__pycache__/\n"


def test_batch_patches_apply_multiple_files_deterministically(tmp_path):
    """Verify applying a batch of multiple approved patches across files."""
    file1 = tmp_path / "config.py"
    file1.write_text('API_KEY = "secret"\nDEBUG = True\n', encoding="utf-8")
    file2 = tmp_path / "main.py"
    file2.write_text('host = "127.0.0.1"\n', encoding="utf-8")

    patches = [
        Patch(
            file="config.py",
            old='API_KEY = "secret"',
            new='API_KEY = os.getenv("API_KEY", "")',
            reason="Move secret",
            status=PatchStatusEnum.APPROVED,
        ),
        Patch(
            file="config.py",
            old="DEBUG = True",
            new="DEBUG = False",
            reason="Disable debug",
            status=PatchStatusEnum.APPROVED,
        ),
        Patch(
            file="main.py",
            old='host = "127.0.0.1"',
            new='host = "0.0.0.0"',
            reason="Bind all interfaces",
            status=PatchStatusEnum.APPROVED,
        ),
    ]

    applied_list = apply_patches(patches, tmp_path)
    assert len(applied_list) == 3
    assert all(p.status == PatchStatusEnum.APPLIED for p in applied_list)

    assert file1.read_text(encoding="utf-8") == 'API_KEY = os.getenv("API_KEY", "")\nDEBUG = False\n'
    assert file2.read_text(encoding="utf-8") == 'host = "0.0.0.0"\n'


def test_failed_patch_in_batch_leaves_entire_workspace_unchanged(tmp_path):
    """Verify transactional behavior: if any patch in a batch fails, no files are modified on disk."""
    file1 = tmp_path / "config.py"
    file1_original = 'API_KEY = "secret"\n'
    file1.write_text(file1_original, encoding="utf-8")

    file2 = tmp_path / "main.py"
    file2_original = 'host = "127.0.0.1"\n'
    file2.write_text(file2_original, encoding="utf-8")

    patches = [
        Patch(
            file="config.py",
            old='API_KEY = "secret"',
            new='API_KEY = os.getenv("API_KEY", "")',
            reason="Valid patch",
            status=PatchStatusEnum.APPROVED,
        ),
        Patch(
            file="main.py",
            old='host = "999.999.999.999"',  # Mismatch! Will fail exact match.
            new='host = "0.0.0.0"',
            reason="Mismatch patch",
            status=PatchStatusEnum.APPROVED,
        ),
    ]

    with pytest.raises(PatchMatchError):
        apply_patches(patches, tmp_path)

    # Assert BOTH files on disk were left 100% UNMODIFIED
    assert file1.read_text(encoding="utf-8") == file1_original
    assert file2.read_text(encoding="utf-8") == file2_original


def test_unified_diff_generation_and_secret_redaction():
    """Verify that unified diff generation produces standard diff format and redacts sensitive keys."""
    raw_secret = "AIzaSyFakeSecretKey1234567890abcdefghij"
    old_code = f'API_KEY = "{raw_secret}"\n'
    new_code = 'API_KEY = os.getenv("API_KEY", "")\n'

    diff = generate_unified_diff(old_code, new_code, from_file="a/config.py", to_file="b/config.py", redact=True)

    assert "--- a/config.py" in diff
    assert "+++ b/config.py" in diff
    assert "-API_KEY =" in diff
    assert "+API_KEY =" in diff
    # Assert raw secret is REDACTED in the generated diff
    assert raw_secret not in diff
    assert "[REDACTED]" in diff


def test_generate_patch_diff_with_workspace_context(tmp_path):
    """Verify generate_patch_diff computes full file context diff when workspace is provided."""
    target_file = tmp_path / "config.py"
    target_file.write_text('APP_NAME = "TestApp"\nPORT = 8000\n', encoding="utf-8")

    patch_obj = Patch(
        file="config.py",
        old="PORT = 8000",
        new='PORT = int(os.getenv("PORT", "8000"))',
        reason="Dynamic port",
        status=PatchStatusEnum.SUGGESTED,
    )

    diff = generate_patch_diff(patch_obj, workspace_dir=tmp_path)
    assert "--- a/config.py" in diff
    assert "+++ b/config.py" in diff
    assert "-APP_NAME = \"TestApp\"" not in diff  # Unchanged lines kept intact
    assert "-PORT = 8000" in diff
    assert '+PORT = int(os.getenv("PORT", "8000"))' in diff
