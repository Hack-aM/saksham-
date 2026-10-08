"""Saksham Configuration and Settings Management Module.

Loads environment variables, validates required credentials (GitHub PAT,
Gemini API key, Render API key), and provides typed configuration objects.
"""

import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present in the workspace root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


from schemas import SeverityEnum

# Deploy Readiness Score weights per issue severity (PRD section 17, NC-7, TASKS.md T13)
ISSUE_SEVERITY_DEDUCTIONS = {
    SeverityEnum.HIGH: 30,
    SeverityEnum.MEDIUM: 15,
    SeverityEnum.LOW: 5,
}


class ConfigurationError(ValueError):
    """Raised when a required configuration variable is missing or invalid."""
    pass


class Settings:
    """Application configuration settings with validation."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        github_token: Optional[str] = None,
        render_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        port: Optional[int] = None,
        environment: Optional[str] = None,
        db_path: Optional[str] = None,
        max_upload_size_bytes: Optional[int] = None,
        gitleaks_path: Optional[str] = None,
    ) -> None:
        self.gitleaks_path: str = (
            gitleaks_path
            or os.getenv("GITLEAKS_PATH", "").strip()
        )
        self.gemini_api_key: str = (
            gemini_api_key
            or os.getenv("GEMINI_API_KEY", "").strip()
        )
        self.github_token: str = (
            github_token
            or os.getenv("GITHUB_TOKEN", "").strip()
        )
        self.render_api_key: str = (
            render_api_key
            or os.getenv("RENDER_API_KEY", "").strip()
        )
        self.gemini_model: str = (
            gemini_model
            or os.getenv("GEMINI_MODEL", "").strip()
        )
        self.port: int = port or int(os.getenv("PORT", "8000"))
        self.environment: str = (
            environment
            or os.getenv("ENVIRONMENT", "development").strip()
        )
        self.db_path: str = (
            db_path
            or os.getenv("DB_PATH", str(BASE_DIR / "saksham.db")).strip()
        )
        self.max_upload_size_bytes: int = (
            max_upload_size_bytes
            or int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(25 * 1024 * 1024)))
        )  # 25 MB compressed limit
        self.max_uncompressed_size_bytes: int = (
            int(os.getenv("MAX_UNCOMPRESSED_SIZE_BYTES", str(100 * 1024 * 1024)))
        )  # 100 MB uncompressed limit (zip bomb protection)
        self.max_extracted_files: int = (
            int(os.getenv("MAX_EXTRACTED_FILES", "10000"))
        )  # 10,000 files max (zip bomb protection)
        self.workspace_ttl_seconds: int = (
            int(os.getenv("WORKSPACE_TTL_SECONDS", "1800"))
        )  # 30 minutes TTL for active runs
        self.max_scan_file_size_bytes: int = (
            int(os.getenv("MAX_SCAN_FILE_SIZE_BYTES", str(1024 * 1024)))
        )  # 1 MB max file size for static AST scanning

    def validate_required_keys(self) -> None:
        """Validate that all mandatory API keys and model names are provided and non-empty.

        Raises:
            ConfigurationError: If any mandatory key is missing.
        """
        missing = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.gemini_model:
            missing.append("GEMINI_MODEL")
        if not self.github_token:
            missing.append("GITHUB_TOKEN")
        if not self.render_api_key:
            missing.append("RENDER_API_KEY")

        if missing:
            raise ConfigurationError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Please define them in your .env file or environment."
            )


_settings: Optional[Settings] = None


def get_settings(force_reload: bool = False) -> Settings:
    """Get or create the singleton Settings instance.

    Args:
        force_reload: If True, re-instantiates Settings from the current environment.

    Returns:
        Settings: The active configuration object.
    """
    global _settings
    if _settings is None or force_reload:
        _settings = Settings()
    return _settings
