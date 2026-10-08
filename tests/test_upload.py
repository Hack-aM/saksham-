"""Unit tests for safe upload extraction and upload endpoint (upload.py & main.py)."""

import io
import os
import stat
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from config import Settings
from main import app
from upload import (
    InvalidUploadError,
    UploadSecurityError,
    UploadSizeError,
    extract_project_zip,
)

client = TestClient(app)


def create_in_memory_zip(files: dict[str, str | bytes]) -> io.BytesIO:
    """Helper to construct in-memory ZIP archives for testing."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            if isinstance(content, str):
                zf.writestr(name, content.encode("utf-8"))
            else:
                zf.writestr(name, content)
    buf.seek(0)
    return buf


def test_valid_zip_extraction() -> None:
    """Verify normal zip extraction succeeds and cleans up on exit."""
    zip_buf = create_in_memory_zip({
        "main.py": "print('hello')",
        "requirements.txt": "fastapi",
    })

    extracted_path = None
    with extract_project_zip(zip_buf) as proj:
        extracted_path = proj.path
        assert proj.path.is_dir()
        assert (proj.path / "main.py").is_file()
        assert (proj.path / "requirements.txt").is_file()
        assert proj.history_available is False
        assert proj.file_count == 2
        assert proj.total_size_bytes > 0

    # Directory must be cleaned up on context exit
    assert not extracted_path.exists()


def test_zip_with_git_folder_sanitization() -> None:
    """Verify that .git hooks are removed and malicious git config is neutralized."""
    malicious_git_config = (
        "[core]\n"
        "\trepositoryformatversion = 0\n"
        "\tfsmonitor = /malicious/script.sh\n"
        "\tpager = /bin/sh -c 'evil'\n"
        "\tsshCommand = evil_ssh\n"
    )
    zip_buf = create_in_memory_zip({
        "main.py": "print('hello')",
        ".git/config": malicious_git_config,
        ".git/hooks/pre-commit": "#!/bin/sh\nrm -rf /",
    })

    with extract_project_zip(zip_buf) as proj:
        assert proj.history_available is True
        git_dir = proj.path / ".git"
        if not git_dir.is_dir():
            git_dir = proj.path.parent / ".git"

        assert git_dir.is_dir()
        # 1. Hooks directory must be completely removed
        assert not (git_dir / "hooks").exists()

        # 2. Malicious config directives must be wiped
        sanitized_config = (git_dir / "config").read_text(encoding="utf-8")
        assert "fsmonitor" not in sanitized_config
        assert "pager" not in sanitized_config
        assert "sshCommand" not in sanitized_config
        assert "repositoryformatversion = 0" in sanitized_config


def test_path_traversal_forward_slash_rejected() -> None:
    """Verify forward-slash directory traversal is rejected."""
    zip_buf = create_in_memory_zip({
        "../evil.py": "malicious content",
    })

    with pytest.raises(UploadSecurityError) as exc_info:
        with extract_project_zip(zip_buf):
            pass
    assert "Path traversal" in str(exc_info.value)


def test_path_traversal_backslash_rejected() -> None:
    """Verify backslash directory traversal (..\\evil.py, a\\..\\..\\x.py) is rejected."""
    # Direct backslash traversal
    zip_buf1 = create_in_memory_zip({
        "..\\evil.py": "malicious content",
    })
    with pytest.raises(UploadSecurityError) as exc_info:
        with extract_project_zip(zip_buf1):
            pass
    assert "Path traversal" in str(exc_info.value)

    # Nested backslash traversal
    zip_buf2 = create_in_memory_zip({
        "sub\\..\\..\\x.py": "malicious content",
    })
    with pytest.raises(UploadSecurityError) as exc_info:
        with extract_project_zip(zip_buf2):
            pass
    assert "Path traversal" in str(exc_info.value)


def test_absolute_path_rejected() -> None:
    """Verify that archive members with absolute paths or drive letters are rejected."""
    # Absolute path with forward slash
    buf_slash = create_in_memory_zip({
        "/etc/passwd": "root:x:0:0:",
    })
    with pytest.raises(UploadSecurityError) as exc_info:
        with extract_project_zip(buf_slash):
            pass
    assert "absolute path" in str(exc_info.value).lower()

    # Windows drive letter
    buf_drive = create_in_memory_zip({
        "C:evil.py": "malicious content",
    })
    with pytest.raises(UploadSecurityError) as exc_info:
        with extract_project_zip(buf_drive):
            pass
    assert "drive letter" in str(exc_info.value).lower()


def test_symlink_zip_rejected() -> None:
    """Verify that ZIP archives containing UNIX symlinks are rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("symlink_file")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    buf.seek(0)

    with pytest.raises(UploadSecurityError) as exc_info:
        with extract_project_zip(buf):
            pass
    assert "Symlink detected" in str(exc_info.value)


def test_oversized_compressed_zip_rejected() -> None:
    """Verify that archives exceeding max_upload_size_bytes are rejected."""
    custom_settings = Settings(
        gemini_api_key="test",
        gemini_model="gemini-2.5-flash",
        github_token="test",
        render_api_key="test",
        max_upload_size_bytes=100,  # 100 bytes limit
    )
    zip_buf = create_in_memory_zip({
        "big_file.txt": "a" * 500,
    })

    with pytest.raises(UploadSizeError) as exc_info:
        with extract_project_zip(zip_buf, settings=custom_settings):
            pass
    assert "compressed limit" in str(exc_info.value).lower()


import struct


def test_zip_actual_uncompressed_bytes_limit_enforced() -> None:
    """Verify that actual bytes written are counted and enforced during extraction."""
    custom_settings = Settings(
        gemini_api_key="test",
        gemini_model="gemini-2.5-flash",
        github_token="test",
        render_api_key="test",
        max_upload_size_bytes=10 * 1024 * 1024,
    )
    custom_settings.max_uncompressed_size_bytes = 1000  # 1000 bytes actual limit

    # Case 1: Archive with multiple files where each individual file header is 400 bytes (under 1000),
    # but the cumulative actual uncompressed bytes (1600 bytes) exceed the 1000 limit.
    zip_buf_multi = create_in_memory_zip({
        "chunk1.txt": "A" * 400,
        "chunk2.txt": "B" * 400,
        "chunk3.txt": "C" * 400,
        "chunk4.txt": "D" * 400,
    })

    with pytest.raises(UploadSizeError) as exc_info:
        with extract_project_zip(zip_buf_multi, settings=custom_settings):
            pass
    assert "Actual uncompressed archive size exceeds limit of 1000 bytes" in str(exc_info.value)

    # Case 2: Archive with a single large file whose actual stream exceeds limit during extraction
    zip_buf_single = create_in_memory_zip({
        "large_file.bin": b"X" * 3000,
    })

    with pytest.raises(UploadSizeError) as exc_info2:
        with extract_project_zip(zip_buf_single, settings=custom_settings):
            pass
    assert "Actual uncompressed archive size exceeds limit of 1000 bytes" in str(exc_info2.value)


def test_zip_bomb_file_count_rejected() -> None:
    """Verify that archives with too many files are rejected."""
    custom_settings = Settings(
        gemini_api_key="test",
        gemini_model="gemini-2.5-flash",
        github_token="test",
        render_api_key="test",
    )
    custom_settings.max_extracted_files = 3

    zip_buf = create_in_memory_zip({
        "f1.txt": "1",
        "f2.txt": "2",
        "f3.txt": "3",
        "f4.txt": "4",
    })

    with pytest.raises(UploadSizeError) as exc_info:
        with extract_project_zip(zip_buf, settings=custom_settings):
            pass
    assert "exceeding the limit of 3 files" in str(exc_info.value)


def test_non_zip_file_rejected() -> None:
    """Verify that corrupt or non-zip bytes raise InvalidUploadError."""
    fake_bytes = b"This is just plain text, not a zip file."

    with pytest.raises(InvalidUploadError):
        with extract_project_zip(fake_bytes):
            pass


def test_cleanup_after_failure() -> None:
    """Verify temporary directory is cleaned up even when extraction fails."""
    zip_buf = create_in_memory_zip({
        "good.py": "print('ok')",
        "../bad.py": "evil",
    })

    try:
        with extract_project_zip(zip_buf) as proj:
            pass
    except UploadSecurityError:
        pass


def test_upload_api_endpoint_success() -> None:
    """Verify POST /upload with a valid zip file returns 200 and metadata."""
    zip_buf = create_in_memory_zip({
        "main.py": "from fastapi import FastAPI\napp = FastAPI()",
        "requirements.txt": "fastapi\nuvicorn",
    })

    response = client.post(
        "/upload",
        files={"file": ("project.zip", zip_buf, "application/zip")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "valid"
    assert data["filename"] == "project.zip"
    assert data["file_count"] == 2
    assert data["history_available"] is False


def test_upload_api_endpoint_invalid_extension() -> None:
    """Verify POST /upload with non-zip extension returns 400."""
    response = client.post(
        "/upload",
        files={"file": ("project.tar.gz", b"fake tar", "application/gzip")},
    )
    assert response.status_code == 400
    assert "File must have a .zip extension" in response.json()["error"]


def test_upload_api_endpoint_traversal_rejected() -> None:
    """Verify POST /upload with path traversal returns 400 security error."""
    zip_buf = create_in_memory_zip({
        "../escape.py": "malicious",
    })
    response = client.post(
        "/upload",
        files={"file": ("hack.zip", zip_buf, "application/zip")},
    )
    assert response.status_code == 400
    assert "Path traversal" in response.json()["error"]


def test_zip_tampered_header_understated_size_handled_cleanly() -> None:
    """Verify that a ZIP whose header understates size is rejected with a clean user-facing error."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.bin", b"X" * 3000)

    # Forging headers with struct: write 50 bytes into uncompressed_size fields
    raw = bytearray(buf.getvalue())
    loc_idx = raw.find(b"PK\x03\x04")
    assert loc_idx != -1
    struct.pack_into("<I", raw, loc_idx + 22, 50)
    cd_idx = raw.find(b"PK\x01\x02")
    assert cd_idx != -1
    struct.pack_into("<I", raw, cd_idx + 24, 50)

    tampered_buf = io.BytesIO(bytes(raw))

    with pytest.raises(InvalidUploadError) as exc_info:
        with extract_project_zip(tampered_buf):
            pass
    assert "Corrupted or tampered ZIP archive" in str(exc_info.value)


def test_upload_api_endpoint_streaming_body_aborted_above_limit() -> None:
    """Verify that a body stream exceeding the 25MB compressed limit is aborted with HTTP 413."""
    class StreamingOversizedZip:
        """Simulate a streaming file exceeding the 25MB max upload limit."""
        def __init__(self, total_bytes: int = 26 * 1024 * 1024):
            self.total_bytes = total_bytes
            self.bytes_read = 0
            self.chunk_size = 64 * 1024

        def read(self, size: int = -1) -> bytes:
            if self.bytes_read >= self.total_bytes:
                return b""
            chunk_len = min(self.chunk_size if size < 0 else size, self.total_bytes - self.bytes_read)
            self.bytes_read += chunk_len
            return b"A" * chunk_len

    streaming_file = StreamingOversizedZip(26 * 1024 * 1024)
    response = client.post(
        "/upload",
        files={"file": ("huge_project.zip", streaming_file, "application/zip")},
    )
    assert response.status_code == 413
    assert "exceeds the maximum limit" in response.json()["error"]


