import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

# Import all SQLAlchemy models to prevent mapper configuration errors
from app.models.chat import ChatSession
from app.models.document import Document
from app.models.medical_image import MedicalImage

from app.services.privacy import export_user_data, purge_user_data, _document_file_candidates

@pytest.fixture
def phase1_env():
    """Dummy fixture to prevent conftest.py reset_test_db from reloading modules."""
    return None

@pytest.mark.asyncio
async def test_export_user_data(phase1_env):
    mock_db = AsyncMock(spec=AsyncSession)
    
    mock_session = ChatSession(id=1, user_id="user-1", title="test session")
    
    mock_sessions_scalar = MagicMock()
    mock_sessions_scalar.scalars.return_value.all.return_value = [mock_session]
    
    mock_other_scalar = MagicMock()
    mock_other_scalar.scalars.return_value.all.return_value = []
    
    mock_db.execute.side_effect = [
        mock_sessions_scalar, # sessions
        mock_other_scalar,    # messages
        mock_other_scalar,    # documents
        mock_other_scalar,    # images
        mock_other_scalar,    # workflows
        mock_other_scalar,    # feedback
        mock_other_scalar     # audit
    ]
    
    res = await export_user_data(mock_db, "user-1")
    assert res["user_id"] == "user-1"
    assert len(res["sessions"]) == 1
    assert res["sessions"][0]["id"] == 1

@pytest.mark.asyncio
async def test_purge_user_data(phase1_env):
    mock_db = AsyncMock(spec=AsyncSession)
    
    mock_session = ChatSession(id=1, user_id="user-1", title="test session")
    mock_doc = Document(id=10, user_id="user-1", filename="test.txt", file_type="txt")
    mock_doc.storage_asset = None
    mock_doc.metadata_ = {"original_suffix": ".txt"}
    
    mock_image = MedicalImage(id=20, user_id="user-1", filename="img.png")
    mock_image.storage_asset = None
    mock_image.thumbnail_asset = None
    mock_image.file_path = "/tmp/img.png"
    mock_image.thumbnail_path = "/tmp/thumb.png"
    
    mock_sessions_scalar = MagicMock()
    mock_sessions_scalar.scalars.return_value.all.return_value = [mock_session]
    
    mock_messages_scalar = MagicMock()
    mock_messages_scalar.scalars.return_value.all.return_value = []
    
    mock_feedback_rows = MagicMock()
    mock_feedback_rows.fetchall.return_value = []
    
    mock_workflow_rows = MagicMock()
    mock_workflow_rows.fetchall.return_value = []
    
    mock_docs_scalar = MagicMock()
    mock_docs_scalar.scalars.return_value.all.return_value = [mock_doc]
    
    mock_images_scalar = MagicMock()
    mock_images_scalar.scalars.return_value.all.return_value = [mock_image]
    
    mock_feedback_rows_2 = MagicMock()
    mock_feedback_rows_2.fetchall.return_value = []
    
    mock_audit_rows = MagicMock()
    mock_audit_rows.fetchall.return_value = []
    
    mock_workflows_rows_2 = MagicMock()
    mock_workflows_rows_2.fetchall.return_value = []
    
    mock_db.execute.side_effect = [
        mock_sessions_scalar,  # select ChatSession
        mock_messages_scalar,  # select ChatMessage
        mock_feedback_rows,    # select UserFeedback.id by session_ids
        None,                  # delete UserFeedback by session_ids
        mock_workflow_rows,    # select Workflow.id by session_ids
        None,                  # delete Workflow by session_ids
        mock_docs_scalar,      # select Document
        mock_images_scalar,    # select MedicalImage
        mock_feedback_rows_2,  # select UserFeedback.id by user_id
        None,                  # delete UserFeedback by user_id
        mock_audit_rows,       # select AuditLog.id
        None,                  # delete AuditLog
        mock_workflows_rows_2, # select Workflow.id by user_id
        None,                  # delete Workflow by user_id
    ]
    
    mock_vec = MagicMock()
    mock_vec.mark_document_deleted.return_value = 1
    
    mock_bm25 = MagicMock()
    mock_bm25.mark_document_deleted.return_value = 1
    
    mock_img_proc = MagicMock()
    
    with (
        patch("app.services.privacy.vector_store_service", mock_vec),
        patch("app.services.privacy.bm25_index", mock_bm25),
        patch("app.services.privacy.image_processing_service", mock_img_proc),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.unlink") as mock_unlink,
    ):
        res = await purge_user_data(mock_db, "user-1")
        assert res["sessions"] == 1
        assert res["documents"] == 1
        assert res["images"] == 1
        assert res["vector_tombstones"] == 1
        assert res["bm25_tombstones"] == 1
        mock_img_proc.delete_image.assert_called_once_with("/tmp/img.png", "/tmp/thumb.png")
        assert mock_unlink.call_count >= 1

@pytest.mark.asyncio
async def test_purge_user_data_with_storage(phase1_env):
    mock_db = AsyncMock(spec=AsyncSession)
    
    mock_doc = Document(id=10, user_id="user-1", filename="test.txt", file_type="txt")
    mock_doc_storage = MagicMock()
    mock_doc_storage.bucket = "doc-bucket"
    mock_doc_storage.object_key = "doc-key"
    mock_doc_storage.storage_metadata = {}
    mock_doc.storage_asset = mock_doc_storage
    
    mock_image = MedicalImage(id=20, user_id="user-1", filename="img.png")
    mock_img_storage = MagicMock()
    mock_img_storage.bucket = "img-bucket"
    mock_img_storage.object_key = "img-key"
    mock_img_storage.storage_metadata = {}
    mock_image.storage_asset = mock_img_storage
    
    mock_thumb_storage = MagicMock()
    mock_thumb_storage.bucket = "thumb-bucket"
    mock_thumb_storage.object_key = "thumb-key"
    mock_thumb_storage.storage_metadata = {}
    mock_image.thumbnail_asset = mock_thumb_storage
    
    mock_sessions_scalar = MagicMock()
    mock_sessions_scalar.scalars.return_value.all.return_value = []
    
    mock_docs_scalar = MagicMock()
    mock_docs_scalar.scalars.return_value.all.return_value = [mock_doc]
    
    mock_images_scalar = MagicMock()
    mock_images_scalar.scalars.return_value.all.return_value = [mock_image]
    
    mock_empty_rows = MagicMock()
    mock_empty_rows.fetchall.return_value = []
    
    mock_db.execute.side_effect = [
        mock_sessions_scalar,  # ChatSession
        mock_docs_scalar,      # Document
        mock_images_scalar,    # MedicalImage
        mock_empty_rows,       # UserFeedback
        None,                  # delete UserFeedback
        mock_empty_rows,       # AuditLog
        None,                  # delete AuditLog
        mock_empty_rows,       # Workflow
        None,                  # delete Workflow
    ]
    
    mock_vec = MagicMock()
    mock_vec.mark_document_deleted.return_value = 1
    
    mock_bm25 = AsyncMock()
    mock_bm25.mark_document_deleted.return_value = 1
    
    mock_storage = AsyncMock()
    
    with (
        patch("app.services.privacy.vector_store_service", mock_vec),
        patch("app.services.privacy.bm25_index", mock_bm25),
        patch("app.services.privacy.storage_service", mock_storage)
    ):
        res = await purge_user_data(mock_db, "user-1")
        assert res["documents"] == 1
        assert res["images"] == 1
        assert mock_storage.delete.call_count == 3

def test_document_file_candidates():
    mock_doc = Document(id="doc-123", user_id="user-1", filename="test.pdf", file_type="pdf")
    mock_doc.metadata_ = None
    
    candidates = _document_file_candidates(mock_doc)
    assert len(candidates) >= 1
    assert candidates[0].name == "doc-123.pdf"
