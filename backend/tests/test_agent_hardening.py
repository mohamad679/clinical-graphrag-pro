import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid

# Import all SQLAlchemy models to prevent mapper configuration errors

from app.services.agent import AgentOrchestrator

@pytest.fixture
def phase1_env():
    """Dummy fixture to prevent conftest.py reset_test_db from reloading modules."""
    return None

def test_agent_routes_and_verification_attempts(phase1_env):
    orchestrator = AgentOrchestrator()
    
    # 1. Test verification attempts
    state = {
        "events": [
            {"type": "workflow_start"},
            {"type": "verification"},
            {"type": "verification"}
        ]
    }
    assert orchestrator._verification_attempts(state) == 2
    
    # 2. Test routes after execute
    state_execute_1 = {
        "current_step": 1,
        "plan": [{"tool": "t1"}, {"tool": "t2"}]
    }
    assert orchestrator._route_after_execute(state_execute_1) == "execute_step_node"
    
    state_execute_2 = {
        "current_step": 2,
        "plan": [{"tool": "t1"}, {"tool": "t2"}]
    }
    assert orchestrator._route_after_execute(state_execute_2) == "synthesize_node"
    
    # 3. Test routes after verify
    state_verify_passed = {
        "verification_passed": True,
        "events": []
    }
    assert orchestrator._route_after_verify(state_verify_passed) == "end"
    
    state_verify_failed_attempts_1 = {
        "verification_passed": False,
        "events": [{"type": "verification"}]
    }
    assert orchestrator._route_after_verify(state_verify_failed_attempts_1) == "retry_synthesis"
    
    state_verify_failed_attempts_2 = {
        "verification_passed": False,
        "events": [{"type": "verification"}, {"type": "verification"}]
    }
    assert orchestrator._route_after_verify(state_verify_failed_attempts_2) == "end"

@pytest.mark.asyncio
async def test_agent_db_logging_helpers(phase1_env):
    orchestrator = AgentOrchestrator()
    
    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    
    w_id = str(uuid.uuid4())
    s_id = str(uuid.uuid4())
    
    with patch("app.services.agent.async_session_factory", mock_factory):
        # 1. _create_workflow
        await orchestrator._create_workflow(
            workflow_id=w_id,
            query="test query",
            workflow_type="general",
            image_id="img-123",
            session_id=s_id,
            user_id="user-1"
        )
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.reset_mock()
        
        # 2. _create_step
        step_id = await orchestrator._create_step(
            workflow_id=w_id,
            step_number=1,
            phase="planning",
            title="Step 1",
            description="Run calculation"
        )
        assert isinstance(step_id, str)
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.reset_mock()
        
        # 3. _update_step
        await orchestrator._update_step(step_id, status="completed")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.reset_mock()
        
        # 4. _create_tool_call
        await orchestrator._create_tool_call(
            step_id=step_id,
            tool_name="bmi_calculator",
            params={"w": 70},
            result={"res": 22.9},
            success=True,
            latency_ms=12.5
        )
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.reset_mock()
        
        # 5. _update_workflow
        await orchestrator._update_workflow(w_id, status="completed")
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.reset_mock()
        
        # 6. _complete_workflow
        await orchestrator._complete_workflow(
            workflow_id=w_id,
            final_answer="A safe response",
            verification_payload={"passed": True}
        )
        assert mock_session.execute.call_count == 1
        assert mock_session.commit.call_count == 1
        mock_session.reset_mock()
        
        # 7. _fail_workflow
        await orchestrator._fail_workflow(w_id, "an error occurred")
        assert mock_session.execute.call_count == 1
        assert mock_session.commit.call_count == 1
