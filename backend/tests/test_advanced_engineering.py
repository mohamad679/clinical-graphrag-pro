import pytest
import os
import sys
import tempfile
import json

# Add repository root to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import MagicMock, patch

from app.services.cost_estimator import calculate_llm_cost
from app.core.config import Settings
from app.core.caching import make_cache_key, CacheManager
from app.services.llm import LLMService
from scripts.generate_synthetic_clinical_data import generate_synthetic_data



def test_cost_calculation():
    # Test valid calculations
    assert calculate_llm_cost("groq", "llama-3.3-70b-versatile", 1000, 500) == 0.000985
    assert calculate_llm_cost("gemini", "gemini-2.0-flash", 1000, 500) == 0.000225
    assert calculate_llm_cost("gemini", "gemini-1.5-pro", 10000, 5000) == 0.0375
    
    # Test local models are free
    assert calculate_llm_cost("ollama", "llama3", 100000, 50000) == 0.0
    assert calculate_llm_cost("llama_cpp", "custom-model", 1000, 500) == 0.0
    assert calculate_llm_cost("local_hf", "custom", 1000, 500) == 0.0

    # Test unknown fallbacks
    assert calculate_llm_cost("custom", "unsupported-model", 1000, 500) == "unknown"
    assert calculate_llm_cost("groq", "llama-3.3-70b-versatile", None, 500) == "unknown"


def test_local_provider_config():
    # Test settings validator accepts local LLMs
    settings = Settings(llm_provider="ollama", local_llm_model="phi3")
    assert settings.llm_provider == "ollama"
    assert settings.local_llm_model == "phi3"

    settings_cpp = Settings(llm_provider="llama_cpp")
    assert settings_cpp.llm_provider == "llama_cpp"


@pytest.mark.asyncio
async def test_local_llm_health_probe():
    service = LLMService()
    
    # Mock settings.llm_provider to ollama
    with patch("app.services.llm.settings.llm_provider", "ollama"), \
         patch("app.services.llm.settings.ollama_url", "http://localhost:11434"), \
         patch("httpx.AsyncClient.get") as mock_get:
         
        mock_get.return_value = MagicMock(status_code=200)
        res = await service.health_check()
        assert res["status"] == "healthy"
        assert res["provider"] == "ollama"


def test_cache_key_isolation():
    # Valid secure keys
    key1 = make_cache_key("retrieval", "patient-1", "tenant-1", {"query": "test"})
    key2 = make_cache_key("retrieval", "patient-2", "tenant-1", {"query": "test"})
    key3 = make_cache_key("retrieval", "patient-1", "tenant-2", {"query": "test"})

    assert key1 != key2
    assert key1 != key3
    assert "tenant-1" in key1
    assert "patient-1" in key1

    # Security error when missing patient/tenant parameters on scoped queries
    with pytest.raises(ValueError) as exc:
        make_cache_key("retrieval", None, "tenant-1", {"query": "test"})
    assert "Security violation" in str(exc.value)

    with pytest.raises(ValueError) as exc2:
        make_cache_key("rerank", "patient-1", None, {"query": "test"})
    assert "Security violation" in str(exc2.value)


def test_cache_disable_behavior():
    CacheManager.clear()
    
    # Store some key
    key = "cgrag:retrieval:tenant-1:patient-1:test-hash"
    CacheManager.set(key, {"data": "val"}, ttl=100)
    
    # Get with cache enabled
    with patch("app.core.caching.settings.cache_enabled", True):
        assert CacheManager.get(key) == {"data": "val"}

    # Get with cache disabled
    with patch("app.core.caching.settings.cache_enabled", False):
        assert CacheManager.get(key) is None


def test_synthetic_data_generator_output():
    with tempfile.TemporaryDirectory() as temp_dir:
        generate_synthetic_data(seed=123, output_dir=temp_dir)
        
        # Verify files exist
        patients_file = os.path.join(temp_dir, "patients.json")
        bundle_file = os.path.join(temp_dir, "fhir_bundle.json")
        notes_file = os.path.join(temp_dir, "patient_clinical_notes.txt")
        adversarial_file = os.path.join(temp_dir, "adversarial_safety_test.txt")

        assert os.path.exists(patients_file)
        assert os.path.exists(bundle_file)
        assert os.path.exists(notes_file)
        assert os.path.exists(adversarial_file)

        # Verify patients prefix
        with open(patients_file) as f:
            patients = json.load(f)
            assert len(patients) > 0
            assert patients[0]["name"][0]["text"].startswith("SYNTHETIC:")

        # Verify bundle transaction format
        with open(bundle_file) as f:
            bundle = json.load(f)
            assert bundle["resourceType"] == "Bundle"
            assert len(bundle["entry"]) > 0
