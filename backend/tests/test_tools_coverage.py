import pytest
import httpx
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.tool_registry import (
    tool_pubmed_search,
    tool_analyze_image,
    tool_search_graph,
    tool_clinical_eval,
    tool_normalize_entities
)

@pytest.mark.asyncio
async def test_tool_pubmed_search():
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = {"esearchresult": {"idlist": ["12345"]}}
    
    mock_summary_resp = MagicMock()
    mock_summary_resp.status_code = 200
    mock_summary_resp.json.return_value = {
        "result": {
            "12345": {
                "title": "Mock Title",
                "source": "Mock Journal",
                "pubdate": "2026"
            }
        }
    }
    
    mock_client.get = AsyncMock(side_effect=[mock_search_resp, mock_summary_resp])
    
    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await tool_pubmed_search("lung cancer", max_results=1)
        assert "results" in res
        assert len(res["results"]) == 1
        assert res["results"][0]["title"] == "Mock Title"
        assert res["results"][0]["id"] == "12345"

@pytest.mark.asyncio
async def test_tool_pubmed_search_error():
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 500
    mock_client.get = AsyncMock(return_value=mock_search_resp)
    
    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await tool_pubmed_search("lung cancer")
        assert "error" in res

@pytest.mark.asyncio
async def test_tool_pubmed_search_no_ids():
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = {"esearchresult": {"idlist": []}}
    mock_client.get = AsyncMock(return_value=mock_search_resp)
    
    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await tool_pubmed_search("lung cancer")
        assert "results" in res
        assert len(res["results"]) == 0

@pytest.mark.asyncio
async def test_tool_analyze_image():
    from app.models.medical_image import MedicalImage
    mock_session = AsyncMock()
    mock_image = MagicMock(spec=MedicalImage)
    mock_image.id = "img-123"
    mock_image.mime_type = "image/png"
    
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = mock_image
    mock_session.execute.return_value = mock_scalar
    
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    
    mock_img_proc = AsyncMock()
    mock_img_proc.read_image_bytes.return_value = b"fakebytes"
    
    mock_vision = AsyncMock()
    mock_vision.analyze_with_question.return_value = "structured response"
    mock_vision.analyze_image.return_value = "full analysis"
    
    with (
        patch("app.core.database.async_session_factory", mock_factory),
        patch("app.services.image_processing.image_processing_service", mock_img_proc),
        patch("app.services.tool_registry.vision_service", mock_vision)
    ):
        res = await tool_analyze_image("img-123", "Is this normal?")
        assert res["image_id"] == "img-123"
        assert res["analysis"] == "structured response"
        
        # Test full analysis without question
        res_full = await tool_analyze_image("img-123")
        assert res_full["analysis"] == "full analysis"
        
        # Test not found
        mock_scalar.scalar_one_or_none.return_value = None
        res_err = await tool_analyze_image("img-123")
        assert "error" in res_err
        
        # Test exception
        mock_factory.side_effect = Exception("db error")
        res_exc = await tool_analyze_image("img-123")
        assert "error" in res_exc

@pytest.mark.asyncio
async def test_tool_analyze_image_file_not_found():
    from app.models.medical_image import MedicalImage
    mock_session = AsyncMock()
    mock_image = MagicMock(spec=MedicalImage)
    mock_image.id = "img-123"
    mock_image.mime_type = "image/png"
    
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = mock_image
    mock_session.execute.return_value = mock_scalar
    
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    
    mock_img_proc = AsyncMock()
    mock_img_proc.read_image_bytes.side_effect = FileNotFoundError("file not found")
    
    with (
        patch("app.core.database.async_session_factory", mock_factory),
        patch("app.services.image_processing.image_processing_service", mock_img_proc)
    ):
        res = await tool_analyze_image("img-123")
        assert "error" in res
        assert "Image file not found" in res["error"]

@pytest.mark.asyncio
async def test_tool_search_graph():
    mock_res = {"nodes": [], "edges": []}
    mock_query = AsyncMock(return_value=mock_res)
    
    with patch("app.services.tool_registry.temporal_graph_service.query_temporal_state", mock_query):
        # Without target_date (defaults to today)
        res = await tool_search_graph("Patient_A", user_id="u123", patient_id="p456")
        assert res == mock_res
        mock_query.assert_called_once()
        
        # With target_date
        res2 = await tool_search_graph("Patient_A", target_date="2026-05-24", user_id="u123", patient_id="p456")
        assert res2 == mock_res

@pytest.mark.asyncio
async def test_tool_clinical_eval_success():
    mock_gen = AsyncMock(return_value='```json\n{"status": "APPROVED", "confidence_score": 0.99}\n```')
    
    with patch("app.services.tool_registry.llm_service.generate", mock_gen):
        res = await tool_clinical_eval("A safe answer", "A source context")
        assert res["status"] == "APPROVED"
        assert res["confidence_score"] == 0.99

@pytest.mark.asyncio
async def test_tool_clinical_eval_json_prefix():
    mock_gen = AsyncMock(return_value='JSON\n{"status": "APPROVED", "confidence_score": 0.99}')
    
    with patch("app.services.tool_registry.llm_service.generate", mock_gen):
        res = await tool_clinical_eval("A safe answer", "A source context")
        assert res["status"] == "APPROVED"
        assert res["confidence_score"] == 0.99

@pytest.mark.asyncio
async def test_tool_clinical_eval_error():
    mock_gen = AsyncMock(return_value='invalid json')
    
    with patch("app.services.tool_registry.llm_service.generate", mock_gen):
        res = await tool_clinical_eval("A safe answer", "A source context")
        assert res["status"] == "REJECTED"
        assert "flags" in res

@pytest.mark.asyncio
async def test_tool_normalize_entities():
    mock_res = MagicMock()
    mock_res.normalized_entities = [
        MagicMock(model_dump=lambda: {"surface_form": "Lisinopril", "concept_id": "C0023688"})
    ]
    mock_res.total = 1
    
    mock_normalize = AsyncMock(return_value=mock_res)
    
    with patch("app.services.entity_normalization.entity_normalization_service.normalize", mock_normalize):
        res = await tool_normalize_entities([{"surface_form": "Lisinopril"}])
        assert res["total"] == 1
        assert res["normalized_entities"][0]["surface_form"] == "Lisinopril"
