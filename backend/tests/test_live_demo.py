import os
import pytest
from unittest.mock import MagicMock, patch

from app.core.config import get_settings, Settings
from app.services.llm import LLMService
from app.services.rag import rag_service, ContextBundle, ContextItem
from app.core.logging_config import redact_secrets

settings = get_settings()


def test_provider_config_validation():
    """Assert ALLOWED_LLM_PROVIDERS contains retrieval-only."""
    from app.core.config import ALLOWED_LLM_PROVIDERS
    assert "retrieval-only" in ALLOWED_LLM_PROVIDERS
    
    # Test mapping of gemini_api_key env variable to google_api_key
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}):
        new_settings = Settings(_env_file=None)
        assert new_settings.google_api_key == "test-gemini-key"



@pytest.mark.asyncio
async def test_missing_gemini_key_behavior():
    """Assert generate_with_metadata throws ValueError if provider is gemini but key is missing."""
    llm = LLMService()
    
    with patch.object(settings, "llm_provider", "gemini"), \
         patch.object(settings, "google_api_key", ""):
        with pytest.raises(ValueError) as exc:
            await llm.generate_with_metadata("test")
        assert "Google Gemini API key is missing" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_groq_key_behavior():
    """Assert generate_with_metadata throws ValueError if provider is groq but key is missing."""
    llm = LLMService()
    
    with patch.object(settings, "llm_provider", "groq"), \
         patch.object(settings, "groq_api_key", ""):
        with pytest.raises(ValueError) as exc:
            await llm.generate_with_metadata("test")
        assert "Groq API key is missing" in str(exc.value)


@pytest.mark.asyncio
async def test_local_hf_disabled_fail_fast():
    """Assert local_hf provider throws a RuntimeError indicating it is not implemented/disabled."""
    llm = LLMService()
    
    with patch.object(settings, "llm_provider", "local_hf"):
        with pytest.raises(RuntimeError) as exc:
            await llm.generate_with_metadata("test")
        assert "local_hf" in str(exc.value)
        assert "is not implemented" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_ollama_server_behavior():
    """Assert connection failures to Ollama raise a clean error message directing startup."""
    llm = LLMService()
    
    with patch.object(settings, "llm_provider", "ollama"), \
         patch.object(settings, "ollama_url", "http://localhost:9999"), \
         patch.object(settings, "local_llm_timeout", 0.1):
        with pytest.raises(RuntimeError) as exc:
            await llm.generate_with_metadata("test")
        assert "Could not connect to Ollama server" in str(exc.value)
        assert "Is Ollama running?" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_ollama_model_404_behavior():
    """Assert 404 response from Ollama (e.g. missing model) raises a clean pull warning."""
    llm = LLMService()
    
    # Mock httpx AsyncClient post to return a 404
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "model not found"
    mock_resp.json = MagicMock(return_value={"error": "model 'llama3' not found, try pulling it"})
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp), \
         patch.object(settings, "llm_provider", "ollama"):
        with pytest.raises(RuntimeError) as exc:
            await llm.generate_with_metadata("test")
        assert "Ollama model" in str(exc.value)
        assert "pull" in str(exc.value)


@pytest.mark.asyncio
async def test_retrieval_only_mode_generation():
    """Assert retrieval-only mode returns summarised context passages without calling the LLM."""
    with patch.object(settings, "llm_provider", "retrieval-only"):
        bundle = ContextBundle(
            mode="retrieval",
            query="test query",
            expanded_queries=[],
            items=[
                ContextItem(
                    citation_id="SRC1",
                    chunk_id="test-chunk-1",
                    document_id="doc-1",
                    document_name="Test Doc 1",
                    chunk_index=0,
                    chunk_text="This is a test document passage detailing vital vital statistics.",
                    retrieval_score=0.82,
                )
            ],
            context_text="This is a test document passage detailing vital vital statistics.",
            reasoning_steps=[],
            retrieval_method="dense",
            total_candidates=1,
            retrieval_latency_ms=10.0,
            context_policy={},
        )
        
        # Call generate_answer
        res = await rag_service.generate_answer(question="test query", bundle=bundle)
        
        assert "Retrieval-only mode" in res.answer
        assert "[SRC1]" in res.answer
        assert res.heuristic_evidence_support_score == 0.82
        assert res.confidence_score == 0.82
        assert res.clinician_review_required is True
        assert res.model_used == "retrieval-only:none"
        assert len(res.sources) == 1
        assert res.sources[0]["document_name"] == "Test Doc 1"


def test_redaction_of_provider_errors():
    """Assert redact_secrets removes API keys and tokens from exception and error strings."""
    secret_url_err = "Client error 400 for url: https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=AIzaSyTestKey123"
    redacted = redact_secrets(secret_url_err)
    assert "AIzaSy" not in redacted
    assert "[REDACTED]" in redacted

    bearer_err = "Failed with headers: Authorization: Bearer gsk_TestKeyGroq456"
    redacted_bearer = redact_secrets(bearer_err)
    assert "gsk_" not in redacted_bearer
    assert "[REDACTED]" in redacted_bearer


@pytest.mark.asyncio
async def test_report_generation():
    """Verify live demo script generates MD and JSON reports successfully."""
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.run_live_demo import compile_markdown_report
    
    mock_results = [
        {
            "query_type": "factual",
            "query": "Is patient stable?",
            "answer": "Yes, patient stable.",
            "confidence_score": 0.9,
            "latency_ms": 150,
            "abstention_status": False,
            "verification_status": "PASSED",
            "citations": [{"marker": "SRC1", "document_name": "chart.txt", "chunk_id": "c1"}],
            "retrieved_chunks": [{"citation_id": "SRC1", "retrieval_score": 0.85, "chunk_text": "Vital signs stable"}],
        }
    ]
    
    md_report = compile_markdown_report("gemini", "gemini-2.0-flash", mock_results)
    assert "# Clinical GraphRAG Pro - Live Demo Report" in md_report
    assert "factual" in md_report.lower()
    assert "gemini-2.0-flash" in md_report
