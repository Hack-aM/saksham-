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
        # Use explicit None sentinel so callers can pass "" to mean "empty / missing".
        # `or` would treat "" as falsy and fall through to os.getenv(), leaking
        # the real credential from .env into test scenarios.
        self.gitleaks_path: str = (
            os.getenv("GITLEAKS_PATH", "").strip() if gitleaks_path is None
            else gitleaks_path.strip()
        )
        self.gemini_api_key: str = (
            os.getenv("GEMINI_API_KEY", "").strip() if gemini_api_key is None
            else gemini_api_key.strip()
        )
        self.github_token: str = (
            os.getenv("GITHUB_TOKEN", "").strip() if github_token is None
            else github_token.strip()
        )
        self.render_api_key: str = (
            os.getenv("RENDER_API_KEY", "").strip() if render_api_key is None
            else render_api_key.strip()
        )
        self.gemini_model: str = (
            os.getenv("GEMINI_MODEL", "").strip() if gemini_model is None
            else gemini_model.strip()
        )
        _port_str: str = os.getenv("PORT", "").strip()
        self.port: int = port if port is not None else (int(_port_str) if _port_str else 8000)
        _env_str: str = os.getenv("ENVIRONMENT", "").strip()
        self.environment: str = (
            environment if environment is not None
            else (_env_str if _env_str else "development")
        )
        _db_default: str = str(BASE_DIR / "saksham.db")
        _db_str: str = os.getenv("DB_PATH", "").strip()
        self.db_path: str = (
            db_path.strip() if db_path is not None
            else (_db_str if _db_str else _db_default)
        )
        self.max_upload_size_bytes: int = (
            max_upload_size_bytes if max_upload_size_bytes is not None
            else int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(25 * 1024 * 1024)))
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
