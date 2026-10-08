"""Saksham Safe Upload Extraction Module.

Handles secure extraction of uploaded project ZIP archives with strict security guardrails:
- Zip bomb protection (compressed size, uncompressed total size on actual written bytes, max file count)
- Path traversal (forward-slash and backslash) and absolute/drive path protection
- Symlink and junction rejection
- Clean temporary directory management with guaranteed cleanup
- Sanitization of .git directory (hooks removed, config replaced with minimal safe version)
"""

import io
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Generator, Optional, Union
from config import Settings, get_settings

SAFE_GIT_CONFIG = """[core]
\trepositoryformatversion = 0
\tfilemode = true
\tbare = false
\tlogallrefupdates = true
"""


class UploadError(Exception):
    """Base exception for upload and extraction failures."""
    pass


class InvalidUploadError(UploadError):
    """Raised when the uploaded file is not a valid ZIP archive."""
    pass


class UploadSizeError(UploadError):
    """Raised when an upload exceeds compressed or uncompressed size limits."""
    pass


class UploadSecurityError(UploadError):
    """Raised when a malicious archive (path traversal, symlink, etc.) is detected."""
    pass


@dataclass
class ExtractedProject:
    """Represents a safely extracted project directory."""
    path: Path
    history_available: bool
    file_count: int
    total_size_bytes: int


def _validate_member_security(info: zipfile.ZipInfo, target_dir: Path) -> None:
    """Inspect a zip member for security violations.

    Raises:
        UploadSecurityError: If path traversal, absolute path, drive path, or symlink is detected.
    """
    raw_name = info.filename

    # Normalize backslashes to forward slashes for cross-platform validation
    normalized_name = raw_name.replace("\\", "/")

    # 1. Reject absolute paths and Windows drive letters
    if raw_name.startswith(("/", "\\")) or normalized_name.startswith("/"):
        raise UploadSecurityError(f"Malicious archive member with absolute path: '{raw_name}'")
    
    if len(raw_name) >= 2 and raw_name[1] == ":":
        raise UploadSecurityError(f"Malicious archive member with drive letter: '{raw_name}'")

    # 2. Check for path traversal components (both forward and backslash)
    parts = normalized_name.split("/")
    if ".." in parts:
        raise UploadSecurityError(f"Path traversal detected in archive member: '{raw_name}'")

    # 3. Check resolved target path stays strictly inside target_dir
    resolved_target = (target_dir / normalized_name).resolve()
    try:
        resolved_target.relative_to(target_dir.resolve())
    except ValueError:
        raise UploadSecurityError(f"Path traversal escape detected for: '{raw_name}'")

    # 4. Reject symlinks / junctions (UNIX S_IFLNK 0o120000)
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise UploadSecurityError(f"Symlink detected in archive member: '{raw_name}'")


def _sanitize_git_directory(git_dir: Path) -> None:
    """Sanitize an extracted .git directory to neutralize malicious configs and hooks.

    - Removes .git/hooks directory if present.
    - Replaces .git/config with minimal safe configuration.
    """
    hooks_dir = git_dir / "hooks"
    if hooks_dir.exists():
        if hooks_dir.is_dir():
            shutil.rmtree(hooks_dir, ignore_errors=True)
        else:
            hooks_dir.unlink(missing_ok=True)

    config_file = git_dir / "config"
    config_file.write_text(SAFE_GIT_CONFIG, encoding="utf-8")


def _extract_to_target_dir(
    source: Union[bytes, io.BytesIO, Path, str],
    target_dir: Path,
    settings: Optional[Settings] = None,
) -> ExtractedProject:
    """Internal helper to validate limits, security, and extract archive into target_dir."""
    cfg = settings or get_settings()

    # Determine input bytes and check compressed size
    if isinstance(source, (str, Path)):
        source_path = Path(source)
        if not source_path.is_file():
            raise InvalidUploadError(f"ZIP file not found: {source_path}")
        compressed_size = source_path.stat().st_size
        if compressed_size > cfg.max_upload_size_bytes:
            raise UploadSizeError(
                f"Uploaded archive size ({compressed_size} bytes) exceeds maximum allowed "
                f"compressed limit of {cfg.max_upload_size_bytes} bytes (25 MB)."
            )
        zip_file_obj: Union[Path, io.BytesIO] = source_path
    elif isinstance(source, (bytes, bytearray)):
        compressed_size = len(source)
        if compressed_size > cfg.max_upload_size_bytes:
            raise UploadSizeError(
                f"Uploaded archive size ({compressed_size} bytes) exceeds maximum allowed "
                f"compressed limit of {cfg.max_upload_size_bytes} bytes (25 MB)."
            )
        zip_file_obj = io.BytesIO(source)
    elif isinstance(source, io.BytesIO):
        source.seek(0, io.SEEK_END)
        compressed_size = source.tell()
        source.seek(0)
        if compressed_size > cfg.max_upload_size_bytes:
            raise UploadSizeError(
                f"Uploaded archive size ({compressed_size} bytes) exceeds maximum allowed "
                f"compressed limit of {cfg.max_upload_size_bytes} bytes (25 MB)."
            )
        zip_file_obj = source
    else:
        raise InvalidUploadError("Unsupported ZIP source format.")

    if not zipfile.is_zipfile(zip_file_obj):
        raise InvalidUploadError("The uploaded file is not a valid ZIP archive.")

    try:
        with zipfile.ZipFile(zip_file_obj, "r") as zf:
            infolist = zf.infolist()
            file_count = len(infolist)

            if file_count > cfg.max_extracted_files:
                raise UploadSizeError(
                    f"Archive contains {file_count} files, exceeding the limit of "
                    f"{cfg.max_extracted_files} files."
                )

            # Security validation pass for all members
            for info in infolist:
                _validate_member_security(info, target_dir)

            total_actual_bytes = 0
            chunk_size = 64 * 1024  # 64 KB chunks

            # Extraction pass with real-time actual written bytes accounting
            for info in infolist:
                normalized_name = info.filename.replace("\\", "/")
                target_path = target_dir / normalized_name

                if info.is_dir() or normalized_name.endswith("/"):
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(info, "r") as src_file, open(target_path, "wb") as dst_file:
                    while True:
                        chunk = src_file.read(chunk_size)
                        if not chunk:
                            break
                        total_actual_bytes += len(chunk)
                        if total_actual_bytes > cfg.max_uncompressed_size_bytes:
                            raise UploadSizeError(
                                f"Actual uncompressed archive size exceeds limit of "
                                f"{cfg.max_uncompressed_size_bytes} bytes (100 MB)."
                            )
                        dst_file.write(chunk)
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        raise InvalidUploadError(f"Corrupted or tampered ZIP archive: {e}")
    except zipfile.error as e:
        raise InvalidUploadError(f"Invalid ZIP archive structure: {e}")

    # Check if project was extracted with a single top-level root folder
    extracted_entries = list(target_dir.iterdir())
    working_dir = target_dir
    if len(extracted_entries) == 1 and extracted_entries[0].is_dir():
        working_dir = extracted_entries[0]

    # Check for .git directory
    git_dir = working_dir / ".git"
    if not git_dir.is_dir():
        git_dir = target_dir / ".git"

    has_git = git_dir.is_dir()
    if has_git:
        _sanitize_git_directory(git_dir)

    return ExtractedProject(
        path=working_dir,
        history_available=has_git,
        file_count=file_count,
        total_size_bytes=total_actual_bytes,
    )


@contextmanager
def extract_project_zip(
    source: Union[bytes, io.BytesIO, Path, str],
    settings: Optional[Settings] = None,
) -> Generator[ExtractedProject, None, None]:
    """Safely extract a ZIP archive into a temporary workspace.

    Enforces:
    - Max compressed size (default 25 MB)
    - Max uncompressed size (default 100 MB) enforced on actual bytes written
    - Max file count (default 10,000 files)
    - Path traversal (forward and backslash) and symlink rejection
    - Automatic temp directory cleanup on normal exit and exceptions
    - Sanitization of .git hooks and config

    Args:
        source: ZIP file content as bytes, BytesIO, or file path.
        settings: Application settings for limits. Defaults to get_settings().

    Yields:
        ExtractedProject: Container with directory Path and metadata.

    Raises:
        InvalidUploadError: If file is not a valid zip archive.
        UploadSizeError: If compressed/uncompressed size or file count limits are exceeded.
        UploadSecurityError: If path traversal or symlinks are detected.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="saksham_run_"))
    try:
        extracted = _extract_to_target_dir(source, temp_dir, settings=settings)
        yield extracted
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def extract_project_to_workspace(
    source: Union[bytes, io.BytesIO, Path, str],
    workspace_dir: Path,
    settings: Optional[Settings] = None,
) -> ExtractedProject:
    """Safely extract a ZIP archive into a persistent run workspace directory.

    Enforces all zip-bomb, security, path traversal checks, and .git sanitization.
    Guarantees cleanup of workspace_dir if extraction fails.

    Args:
        source: ZIP file content as bytes, BytesIO, or file path.
        workspace_dir: Directory where the project should be extracted.
        settings: Application settings for limits.

    Returns:
        ExtractedProject: Container with directory Path and metadata.

    Raises:
        InvalidUploadError: If file is not a valid zip archive.
        UploadSizeError: If compressed/uncompressed size or file count limits are exceeded.
        UploadSecurityError: If path traversal or symlinks are detected.
    """
    target_path = Path(workspace_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)
    try:
        return _extract_to_target_dir(source, target_path, settings=settings)
    except Exception:
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)
        raise
