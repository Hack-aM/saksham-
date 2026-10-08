"""Saksham LLM Client Module.

Google Gemini API wrapper with structured Pydantic schema validation,
timeout handling, provider error translation, and secret redaction guardrails
per ARCHITECTURE.md section 8 and TASKS.md T15.
"""

import json
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError
from google import genai
from google.genai import errors, types

from config import Settings, get_settings
from redact import redact_text

logger = logging.getLogger("saksham.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base exception for all LLM client failures."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when mandatory LLM configuration (API key or model name) is missing."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM request exceeds the configured timeout."""
    pass


class LLMResponseError(LLMError):
    """Raised when an LLM API error occurs or structured response validation fails."""
    pass


def _clean_json_text(raw_text: str) -> str:
    """Clean markdown code fences and whitespace from JSON response text."""
    trimmed = raw_text.strip()
    if trimmed.startswith("```"):
        lines = trimmed.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        trimmed = "\n".join(lines).strip()
    return trimmed


class GeminiLLMClient:
    """Typed client for Google Gemini API models with safety guardrails."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: int = 30,
        settings: Optional[Settings] = None,
    ) -> None:
        """Initialize the Gemini client using settings or explicit parameters.

        Args:
            api_key: Optional explicit Gemini API key.
            model: Optional explicit Gemini model name (e.g. 'gemini-2.5-flash').
            timeout_seconds: Request timeout in seconds (default: 30s).
            settings: Application settings instance.

        Raises:
            LLMConfigurationError: If API key or model name is missing.
        """
        cfg = settings or get_settings()
        self.api_key: str = (api_key or cfg.gemini_api_key or "").strip()
        self.model: str = (model or cfg.gemini_model or "").strip()
        self.timeout_seconds: int = timeout_seconds

        if not self.api_key:
            raise LLMConfigurationError(
                "Missing GEMINI_API_KEY. Please provide a valid Gemini API key in your environment or .env file."
            )
        if not self.model:
            raise LLMConfigurationError(
                "Missing GEMINI_MODEL. Please specify the model name (e.g. 'gemini-2.5-flash') in your environment or .env file."
            )

        # Initialize Google GenAI client with explicit HTTP timeout
        http_options = types.HttpOptions(timeout=self.timeout_seconds * 1000)
        self._client = genai.Client(api_key=self.api_key, http_options=http_options)

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """Generate free-form text response from the Gemini model.

        Args:
            prompt: User prompt content (sanitized, no raw secret tokens).
            system_instruction: Optional system instruction prompt.
            temperature: Sampling temperature (default 0.2 for deterministic code).
            timeout_seconds: Optional per-request timeout override.

        Returns:
            str: Generated text response.

        Raises:
            LLMTimeoutError: If the call times out.
            LLMResponseError: If the API returns an error.
            LLMError: For other unexpected failures.
        """
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )
        if timeout_seconds:
            config.http_options = types.HttpOptions(timeout=timeout_seconds * 1000)

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            if not response or not response.text:
                raise LLMResponseError("Gemini returned an empty response.")
            return response.text
        except errors.APIError as e:
            # Mask any accidental sensitive values in error message
            safe_msg = redact_text(str(e))
            raise LLMResponseError(f"Gemini API error ({e.code}): {safe_msg}") from e
        except (TimeoutError, Exception) as e:
            error_type = type(e).__name__
            if "timeout" in error_type.lower() or "timeout" in str(e).lower():
                raise LLMTimeoutError(f"Gemini request timed out after {timeout_seconds or self.timeout_seconds}s: {redact_text(str(e))}") from e
            safe_msg = redact_text(str(e))
            raise LLMError(f"Gemini client error ({error_type}): {safe_msg}") from e

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        timeout_seconds: Optional[int] = None,
    ) -> T:
        """Generate structured response validated against a Pydantic model.

        Uses native JSON schema enforcement with one automatic repair attempt
        if schema validation fails.

        Args:
            prompt: User prompt content.
            response_model: Target Pydantic model class.
            system_instruction: Optional system instruction prompt.
            temperature: Sampling temperature.
            timeout_seconds: Optional request timeout override.

        Returns:
            T: Validated instance of response_model.

        Raises:
            LLMTimeoutError: If request times out.
            LLMResponseError: If output cannot be parsed into response_model.
        """
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_model,
        )
        if timeout_seconds:
            config.http_options = types.HttpOptions(timeout=timeout_seconds * 1000)

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            raw_text = response.text if response and response.text else ""
            cleaned_json = _clean_json_text(raw_text)
            return response_model.model_validate_json(cleaned_json)
        except (ValidationError, json.JSONDecodeError) as parse_err:
            # Automatic repair attempt: re-prompt with schema error
            logger.warning("Initial structured output validation failed; attempting repair retry.")
            repair_prompt = (
                f"{prompt}\n\n"
                f"Your previous JSON response was invalid and failed schema validation: {str(parse_err)}.\n"
                f"Please output strictly valid JSON conforming exactly to the requested schema."
            )
            try:
                repair_response = self._client.models.generate_content(
                    model=self.model,
                    contents=repair_prompt,
                    config=config,
                )
                repair_text = repair_response.text if repair_response and repair_response.text else ""
                cleaned_repair = _clean_json_text(repair_text)
                return response_model.model_validate_json(cleaned_repair)
            except Exception as retry_err:
                raise LLMResponseError(
                    f"Failed to generate valid structured response for {response_model.__name__}: {redact_text(str(retry_err))}"
                ) from retry_err
        except errors.APIError as e:
            raise LLMResponseError(f"Gemini API error ({e.code}): {redact_text(str(e))}") from e
        except (TimeoutError, Exception) as e:
            error_type = type(e).__name__
            if "timeout" in error_type.lower() or "timeout" in str(e).lower():
                raise LLMTimeoutError(f"Gemini request timed out: {redact_text(str(e))}") from e
            raise LLMError(f"Gemini client failure ({error_type}): {redact_text(str(e))}") from e


def get_llm_client(settings: Optional[Settings] = None) -> GeminiLLMClient:
    """Helper factory to obtain a configured GeminiLLMClient instance."""
    return GeminiLLMClient(settings=settings)
