import pytest
import logging
from app.core.observability import (
    new_request_id,
    new_trace_id,
    new_span_id,
    get_observability_context,
    current_trace_id,
    export_trace_context,
    bind_observability_context,
    update_observability_context,
    trace_operation,
)

def test_id_generators():
    """Verify that request_id, trace_id, and span_id are generated correctly."""
    req_id = new_request_id()
    assert isinstance(req_id, str)
    assert len(req_id) == 12
    
    tr_id = new_trace_id()
    assert isinstance(tr_id, str)
    assert len(tr_id) == 32
    
    sp_id = new_span_id()
    assert isinstance(sp_id, str)
    assert len(sp_id) == 16

def test_context_binding_and_update():
    """Test getting, setting, binding, and exporting trace context."""
    # Test update and get
    update_observability_context(request_id="req-123", user_id="user-456", custom_field="val")
    ctx = get_observability_context()
    assert ctx["request_id"] == "req-123"
    assert ctx["user_id"] == "user-456"
    assert ctx["custom_field"] == "val"
    
    # Test current_trace_id fallback
    tid = current_trace_id()
    assert isinstance(tid, str)
    assert len(tid) == 32
    
    # Test export context only extracts standard keys
    exported = export_trace_context()
    assert exported["request_id"] == "req-123"
    assert exported["user_id"] == "user-456"
    assert "custom_field" not in exported

    # Test bind_observability_context manager
    with bind_observability_context(user_id="user-789", method="POST") as updated:
        assert updated["user_id"] == "user-789"
        assert updated["method"] == "POST"
        assert updated["request_id"] == "req-123"
    
    # Context should be restored
    ctx_restored = get_observability_context()
    assert ctx_restored["user_id"] == "user-456"
    assert "method" not in ctx_restored

def test_trace_operation_emit_start(caplog):
    """Test trace_operation with emit_start=True."""
    caplog.set_level(logging.INFO)
    logger = logging.getLogger("test_trace")
    
    with trace_operation("some_op", component="my_comp", logger_=logger, emit_start=True) as span_ctx:
        assert span_ctx["operation"] == "some_op"
        assert span_ctx["component"] == "my_comp"
        
    # Check start and completion log events
    assert any("span.started" in rec.message for rec in caplog.records)
    assert any("span.completed" in rec.message for rec in caplog.records)

def test_trace_operation_failure(caplog):
    """Test trace_operation when an exception is raised inside the span."""
    logger = logging.getLogger("test_trace_fail")
    
    with pytest.raises(ValueError, match="Span failure"):
        with trace_operation("failed_op", component="my_comp", logger_=logger):
            raise ValueError("Span failure")
            
    # Check failure log event
    assert any("span.failed" in rec.message for rec in caplog.records)
