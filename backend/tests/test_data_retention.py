import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.data_retention import purge_expired_sessions

@pytest.mark.anyio
async def test_purge_expired_sessions():
    mock_settings = MagicMock()
    mock_settings.data_retention_days = 30
    
    # Mock database session
    mock_db = AsyncMock()
    
    # Mock returned sessions
    mock_session1 = MagicMock()
    mock_session1.id = "session-1"
    mock_session2 = MagicMock()
    mock_session2.id = "session-2"
    
    # Mock execute results
    # First query: ChatSession select
    mock_result_sessions = MagicMock()
    mock_result_sessions.scalars.return_value.all.return_value = [mock_session1, mock_session2]
    
    # Second/third query: feedback & workflow selects
    mock_result_feedback = MagicMock()
    mock_result_feedback.fetchall.return_value = [("feedback-1",), ("feedback-2",)]
    mock_result_workflow = MagicMock()
    mock_result_workflow.fetchall.return_value = [("workflow-1",)]
    
    mock_db.execute.side_effect = [
        mock_result_sessions,
        mock_result_feedback,
        mock_result_workflow,
        None, # delete feedback
        None, # delete workflow
    ]
    
    # Mock session factory context manager
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_db
    
    with patch("app.services.data_retention.get_settings", return_value=mock_settings), \
         patch("app.services.data_retention.async_session_factory", mock_factory):
        
        res = await purge_expired_sessions()
        
        assert res["sessions_deleted"] == 2
        assert res["feedback_deleted"] == 2
        assert res["workflows_deleted"] == 1
        assert "cutoff" in res
        
        # Verify db calls
        assert mock_db.delete.call_count == 2
        mock_db.commit.assert_called_once()
