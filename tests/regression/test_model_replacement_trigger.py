"""
Regression tests for Model Replacement triggering.

This test verifies that the RequestProcessor correctly triggers the model 
replacement service even when the initial RequestContext.backend is None,
by correctly resolving the backend from the request model or app defaults.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.services.request_processor_service import RequestProcessor
from src.core.domain.chat import ChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.model_replacement_service_interface import IModelReplacementService


@pytest.mark.asyncio
async def test_replacement_triggers_with_none_context_backend():
    """
    Test that model replacement triggers correctly when context.backend is None.
    
    This is a regression test for the issue where replacement logic was skipped
    because it relied on context.backend which is often populated later.
    """
    # 1. Setup mocks
    mock_replacement = MagicMock(spec=IModelReplacementService)
    # should_replace returns True to trigger replacement
    mock_replacement.should_replace.return_value = True
    mock_replacement.get_state.return_value = MagicMock(active=False)
    mock_replacement.activate_replacement = AsyncMock()
    mock_replacement.get_effective_backend_model.return_value = ("openai", "gpt-4o")
    
    mock_app_state = MagicMock()
    # Simulate a default backend being configured
    mock_app_state.get_backend_type.return_value = "gemini"
    
    # Concrete request
    request_data = ChatRequest(
        model="gemini-3-flash",
        messages=[ChatMessage(role="user", content="hi")]
    )
    
    mock_dependencies = {
        "command_processor": MagicMock(),
        "session_manager": MagicMock(),
        "backend_request_manager": MagicMock(),
        "response_manager": MagicMock(),
        "session_enricher": MagicMock(),
        "request_side_effects": MagicMock(),
        "command_handler": MagicMock(),
        "backend_preparer": MagicMock(),
        "transform_pipeline": MagicMock(),
        "backend_executor": MagicMock(),
        "app_state": mock_app_state,
        "replacement_service": mock_replacement,
    }
    
    # Setup necessary async mocks
    mock_dependencies["session_enricher"].enrich = AsyncMock(return_value=(MagicMock(), request_data))
    mock_dependencies["session_manager"].resolve_session_id = AsyncMock(return_value="test-session")
    mock_dependencies["request_side_effects"].apply = AsyncMock(return_value=request_data)
    mock_dependencies["command_handler"].handle = AsyncMock(return_value=ProcessedResult(
        modified_messages=list(request_data.messages),
        command_executed=False,
        command_results=[]
    ))
    
    # Return the request passed to it to simulate preparation
    mock_dependencies["backend_preparer"].prepare = AsyncMock(side_effect=lambda ctx, sid, req, res: req)
    mock_dependencies["transform_pipeline"].transform = AsyncMock(side_effect=lambda ctx, sess, sid, req: req)
    mock_dependencies["backend_executor"].execute = AsyncMock()
    
    processor = RequestProcessor(**mock_dependencies)
    
    # 2. Create context with backend=None (the state that previously caused the bug)
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        backend=None, 
    )
    
    # 3. Execute
    await processor.process_request(context, request_data)
    
    # 4. Verify that replacement was checked and updated context
    assert mock_replacement.should_replace.called
    assert context.backend == "openai"
    assert context.effective_model == "gpt-4o"
    
    # 5. Verify the executor received the updated request model
    # The last call to transform or execute should have the new model
    call_args = mock_dependencies["backend_executor"].execute.call_args
    passed_request = call_args.args[3]
    assert passed_request.model == "openai:gpt-4o"


@pytest.mark.asyncio
async def test_replacement_resolves_backend_from_model_prefix():
    """
    Test that the backend is correctly resolved from the model name prefix 
    (e.g. 'openai:gpt-4') for replacement checking even if context.backend is None.
    """
    mock_replacement = MagicMock(spec=IModelReplacementService)
    mock_replacement.should_replace.return_value = False # Don't actually replace, just check call args
    
    mock_app_state = MagicMock()
    # Default is different from the prefix to prove prefix takes priority
    mock_app_state.get_backend_type.return_value = "gemini"
    
    request_data = ChatRequest(
        model="anthropic:claude-3",
        messages=[ChatMessage(role="user", content="hi")]
    )
    
    # Setup dependencies (minimal set for the replacement check part)
    mock_deps = {k: MagicMock() for k in [
        "command_processor", "session_manager", "backend_request_manager", 
        "response_manager", "session_enricher", "request_side_effects", 
        "command_handler", "backend_preparer", "transform_pipeline", 
        "backend_executor", "app_state", "replacement_service"
    ]}
    
    # Default async setup
    mock_deps["session_enricher"].enrich = AsyncMock(return_value=(MagicMock(), request_data))
    mock_deps["session_manager"].resolve_session_id = AsyncMock(return_value="test")
    mock_deps["request_side_effects"].apply = AsyncMock(return_value=request_data)
    mock_deps["command_handler"].handle = AsyncMock(return_value=ProcessedResult(
        modified_messages=list(request_data.messages),
        command_executed=False,
        command_results=[]
    ))
    mock_deps["backend_preparer"].prepare = AsyncMock(return_value=request_data)
    mock_deps["transform_pipeline"].transform = AsyncMock(return_value=request_data)
    mock_deps["backend_executor"].execute = AsyncMock()
    mock_deps["app_state"] = mock_app_state
    mock_deps["replacement_service"] = mock_replacement
    
    processor = RequestProcessor(**mock_deps)
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None, backend=None)
    
    await processor.process_request(context, request_data)
    
    # Verify should_replace was called
    # In the fix, original_backend should have been resolved to "anthropic"
    assert mock_replacement.should_replace.called
    # If the bug was present, it wouldn't have been called at all.
