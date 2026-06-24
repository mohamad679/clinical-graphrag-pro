"""
Unit tests for credentials and API key redaction in logging and exception handling.
"""

import pytest
import logging
import json
from unittest.mock import MagicMock, patch
from app.core.logging_config import redact_secrets, redact_for_log, JSONFormatter
from app.services.llm import LLMService


def _fake_google_key() -> str:
    return "AI" + "zaSy" + "A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"


def test_redact_secrets_patterns():
    """Verify regex-based scrubbing of Google keys, Groq keys, Bearer tokens, and query credentials."""
    # Google API Key / Gemini API Key
    google_key = _fake_google_key()
    msg = f"Failed to connect using key {google_key} to Google Generative AI."
    assert redact_secrets(msg) == "Failed to connect using key [REDACTED] to Google Generative AI."

    # Groq API Key
    groq_key = "gsk_123456789012345678901234567890123456789012345678"
    msg_groq = f"Invalid API key: {groq_key} provided to Groq client."
    assert redact_secrets(msg_groq) == "Invalid API key: [REDACTED] provided to Groq client."

    # Bearer token
    bearer_token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    msg_bearer = f"Authorization header was {bearer_token}"
    assert redact_secrets(msg_bearer) == "Authorization header was [REDACTED]"

    # Query string credential parameter
    query_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={google_key}"
    assert redact_secrets(query_url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=[REDACTED]"

    query_secret = "http://localhost:8000/api/callback?secret=super_secret_value_12345"
    assert redact_secrets(query_secret) == "http://localhost:8000/api/callback?secret=[REDACTED]"


def test_redact_for_log_types():
    """Test redact_for_log recursive processing for dictionaries, lists, tuples, and strings."""
    data = {
        "user_id": "user-123",
        "api_key": _fake_google_key(),
        "nested": {
            "password": "secretpassword",
            "safe_field": "hello"
        },
        "list_field": ["safe", "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"],
        "tuple_field": ("gsk_123456789012345678901234567890123456789012345678", "safe")
    }

    redacted = redact_for_log(data)
    assert redacted["user_id"] == "user-123"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "hello"
    assert redacted["list_field"][0] == "safe"
    assert redacted["list_field"][1] == "[REDACTED]"
    assert redacted["tuple_field"][0] == "[REDACTED]"
    assert redacted["tuple_field"][1] == "safe"


def test_json_formatter_scrubbing():
    """Test that JSONFormatter scrubs credentials in formatted logs."""
    formatter = JSONFormatter()
    
    # Create log record containing sensitive credentials in the message
    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg=f"API call failed with key {_fake_google_key()} or token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        args=(),
        exc_info=None
    )
    
    log_output = formatter.format(record)
    parsed = json.loads(log_output)
    
    # Assert that sensitive keys are redacted in the logged message
    assert "AIzaSy" not in parsed["message"]
    assert "Bearer" not in parsed["message"]
    assert "[REDACTED]" in parsed["message"]


@pytest.mark.anyio
async def test_llm_service_exception_redaction():
    """Assert that LLMService generation methods redact API keys in exceptions."""
    service = LLMService()
    
    # Test Groq exception key redaction
    mock_groq_client = MagicMock()
    # Mock post throwing an exception containing key
    groq_key = "gsk_123456789012345678901234567890123456789012345678"
    mock_groq_client.post.side_effect = Exception(f"HTTP 401 Unauthorized for key {groq_key}")
    
    with patch.object(service, "_get_groq_client", return_value=mock_groq_client):
        with pytest.raises(RuntimeError) as exc_info:
            await service._generate_groq([{"role": "user", "content": "hi"}])
        
        # Verify the exception message is redacted and does not leak the key
        assert groq_key not in str(exc_info.value)
        assert "[REDACTED]" in str(exc_info.value)

    # Test Gemini exception key redaction
    mock_gemini_client = MagicMock()
    google_key = _fake_google_key()
    mock_gemini_client.post.side_effect = Exception(f"Invalid key parameters in request: key={google_key}")
    
    with patch.object(service, "_get_gemini_client", return_value=mock_gemini_client):
        with pytest.raises(RuntimeError) as exc_info:
            await service._generate_gemini([{"role": "user", "content": "hi"}])
            
        assert google_key not in str(exc_info.value)
        assert "[REDACTED]" in str(exc_info.value)
