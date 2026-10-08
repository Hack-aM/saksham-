"""Unit tests for Gemini LLM Client in llm.py (T15).

All tests use mocks to ensure no real network or API calls are made to Google Gemini.
"""

from unittest.mock import MagicMock, patch
import pytest
from pydantic import BaseModel, Field

from config import Settings
from llm import (
    GeminiLLMClient,
    LLMConfigurationError,
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    _clean_json_text,
    get_llm_client,
)
from schemas import Patch, PatchStatusEnum


class SampleOutput(BaseModel):
    """Test output schema."""
    summary: str
    confidence: float = Field(default=1.0)


def test_missing_api_key_raises_configuration_error():
    """Verify that initializing client with missing API key raises LLMConfigurationError."""
    settings = Settings(gemini_api_key="", gemini_model="gemini-2.5-flash")
    with pytest.raises(LLMConfigurationError) as exc_info:
        GeminiLLMClient(settings=settings)
    assert "Missing GEMINI_API_KEY" in str(exc_info.value)


def test_missing_model_name_raises_configuration_error():
    """Verify that initializing client with missing model name raises LLMConfigurationError."""
    settings = Settings(gemini_api_key="fake-key-12345", gemini_model="")
    with pytest.raises(LLMConfigurationError) as exc_info:
        GeminiLLMClient(settings=settings)
    assert "Missing GEMINI_MODEL" in str(exc_info.value)


def test_clean_json_text_helper():
    """Verify markdown code fence stripping."""
    raw_with_fence = "```json\n{\"summary\": \"test\"}\n```"
    assert _clean_json_text(raw_with_fence) == '{"summary": "test"}'

    raw_plain = '{"summary": "test"}'
    assert _clean_json_text(raw_plain) == '{"summary": "test"}'


@patch("llm.genai.Client")
def test_successful_text_generation(mock_client_class):
    """Verify free-form text generation passes configured model name and returns text."""
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance

    mock_response = MagicMock()
    mock_response.text = "Here is the explanation for the issue."
    mock_instance.models.generate_content.return_value = mock_response

    settings = Settings(gemini_api_key="fake-key", gemini_model="gemini-2.5-flash")
    client = GeminiLLMClient(settings=settings)

    result = client.generate_text("Explain port configuration")
    assert result == "Here is the explanation for the issue."

    # Verify model name and prompt passed
    mock_instance.models.generate_content.assert_called_once()
    kwargs = mock_instance.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    assert kwargs["contents"] == "Explain port configuration"


@patch("llm.genai.Client")
def test_successful_structured_generation(mock_client_class):
    """Verify structured output parsing into Pydantic model."""
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance

    mock_response = MagicMock()
    mock_response.text = '{"summary": "Fix applied", "confidence": 0.95}'
    mock_instance.models.generate_content.return_value = mock_response

    settings = Settings(gemini_api_key="fake-key", gemini_model="gemini-2.5-flash")
    client = GeminiLLMClient(settings=settings)

    parsed = client.generate_structured(
        prompt="Suggest fix",
        response_model=SampleOutput,
    )
    assert isinstance(parsed, SampleOutput)
    assert parsed.summary == "Fix applied"
    assert parsed.confidence == 0.95


@patch("llm.genai.Client")
def test_structured_generation_with_markdown_fence(mock_client_class):
    """Verify structured parsing succeeds when LLM wraps JSON in markdown fences."""
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance

    mock_response = MagicMock()
    mock_response.text = '```json\n{\n  "file": "config.py",\n  "old": "API_KEY = \\"secret\\"",\n  "new": "API_KEY = os.getenv(\\"API_KEY\\")",\n  "reason": "Protect secret"\n}\n```'
    mock_instance.models.generate_content.return_value = mock_response

    settings = Settings(gemini_api_key="fake-key", gemini_model="gemini-2.5-flash")
    client = GeminiLLMClient(settings=settings)

    patch_obj = client.generate_structured(
        prompt="Fix API key",
        response_model=Patch,
    )
    assert isinstance(patch_obj, Patch)
    assert patch_obj.file == "config.py"
    assert patch_obj.status == PatchStatusEnum.SUGGESTED


@patch("llm.genai.Client")
def test_structured_generation_repair_retry(mock_client_class):
    """Verify that a broken JSON on initial attempt triggers a repair retry that succeeds."""
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance

    bad_response = MagicMock()
    bad_response.text = 'invalid json { broken'

    good_response = MagicMock()
    good_response.text = '{"summary": "Repaired JSON", "confidence": 1.0}'

    mock_instance.models.generate_content.side_effect = [bad_response, good_response]

    settings = Settings(gemini_api_key="fake-key", gemini_model="gemini-2.5-flash")
    client = GeminiLLMClient(settings=settings)

    res = client.generate_structured("Generate sample", SampleOutput)
    assert res.summary == "Repaired JSON"
    assert mock_instance.models.generate_content.call_count == 2


@patch("llm.genai.Client")
def test_timeout_raises_llm_timeout_error(mock_client_class):
    """Verify that request timeout translates to LLMTimeoutError."""
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance
    mock_instance.models.generate_content.side_effect = TimeoutError("Request timed out")

    settings = Settings(gemini_api_key="fake-key", gemini_model="gemini-2.5-flash")
    client = GeminiLLMClient(settings=settings)

    with pytest.raises(LLMTimeoutError) as exc_info:
        client.generate_text("Prompt that hangs")
    assert "timed out" in str(exc_info.value).lower()


@patch("llm.genai.Client")
def test_provider_api_error_handling_and_secret_redaction(mock_client_class):
    """Verify that API errors are wrapped in LLMResponseError and sensitive keys are redacted."""
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance

    from google.genai.errors import APIError
    secret_key = "AIzaSyFakeSecretKey1234567890abcdefghij"
    mock_instance.models.generate_content.side_effect = APIError(
        403,
        {"error": {"message": f"Invalid API Key: {secret_key}"}},
    )

    settings = Settings(gemini_api_key="fake-key", gemini_model="gemini-2.5-flash")
    client = GeminiLLMClient(settings=settings)

    with pytest.raises(LLMResponseError) as exc_info:
        client.generate_text("Prompt that fails")
    
    err_str = str(exc_info.value)
    assert "403" in err_str
    # Confirm raw API key is redacted in exception message
    assert secret_key not in err_str
