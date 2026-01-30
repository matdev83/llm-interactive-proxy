from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    ImageURL,
    MessageContentPartImage,
)
from src.core.domain.model_capabilities import ModelLimits
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.services.backend_preparer import BackendPreparer


@pytest.mark.asyncio
async def test_backend_preparer_capacity_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Setup dependencies
    backend_request_manager = MagicMock()
    backend_request_manager.prepare_backend_request = AsyncMock()

    app_state = MagicMock()
    app_state.get_setting.return_value = SimpleNamespace(
        model_limit_enforcement=SimpleNamespace(enabled=True)
    )
    app_state.get_model_defaults.return_value = {}
    app_state.get_backend_type.return_value = "openai"

    model_catalog = MagicMock()
    # model capacity: context=1000, output=200. Max input allowed = 800.
    model_catalog.get_limits.return_value = ModelLimits(
        context_window=1000, max_output_tokens=200
    )
    model_catalog.get_input_modalities.return_value = None

    preparer = BackendPreparer(backend_request_manager, app_state, model_catalog)

    # Create a request that fits context but not with max output
    # Let's say input is 900 tokens. 900 + 200 = 1100 > 1000. REJECT.
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="hello" * 300)]
    )
    backend_request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="hello" * 300)]
    )
    backend_request_manager.prepare_backend_request.return_value = backend_request

    processed = ProcessedResult(
        modified_messages=[], command_executed=False, command_results=[]
    )
    context = RequestContext(headers={}, cookies={}, state=None, app_state=app_state)

    monkeypatch.setattr(
        "src.core.services.backend_preparer.count_tokens", lambda *_args, **_kwargs: 900
    )

    with pytest.raises(InvalidRequestError) as excinfo:
        await preparer.prepare(context, "session_id", request, processed)

    error_dict = excinfo.value.to_dict()
    assert error_dict["error"]["code"] == "model_capacity_exceeded"
    assert "input size leaves no room for maximum model output" in str(excinfo.value)


@pytest.mark.asyncio
async def test_backend_preparer_capacity_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Setup dependencies
    backend_request_manager = MagicMock()
    backend_request_manager.prepare_backend_request = AsyncMock()

    app_state = MagicMock()
    app_state.get_setting.return_value = SimpleNamespace(
        model_limit_enforcement=SimpleNamespace(enabled=True)
    )
    app_state.get_model_defaults.return_value = {}
    app_state.get_backend_type.return_value = "openai"

    model_catalog = MagicMock()
    # model capacity: context=1000, output=200. Max input allowed = 800.
    model_catalog.get_limits.return_value = ModelLimits(
        context_window=1000, max_output_tokens=200
    )
    model_catalog.get_input_modalities.return_value = None

    preparer = BackendPreparer(backend_request_manager, app_state, model_catalog)

    # Input is 500 tokens. 500 + 200 = 700 <= 1000. ACCEPT.
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="hello")]
    )
    backend_request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="hello")]
    )
    backend_request_manager.prepare_backend_request.return_value = backend_request

    processed = ProcessedResult(
        modified_messages=[], command_executed=False, command_results=[]
    )
    context = RequestContext(headers={}, cookies={}, state=None, app_state=app_state)

    monkeypatch.setattr(
        "src.core.services.backend_preparer.count_tokens", lambda *_args, **_kwargs: 500
    )

    result = await preparer.prepare(context, "session_id", request, processed)
    assert result is not None


@pytest.mark.asyncio
async def test_backend_preparer_rejects_unsupported_modalities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_request_manager = MagicMock()
    backend_request_manager.prepare_backend_request = AsyncMock()

    app_state = MagicMock()
    app_state.get_setting.return_value = SimpleNamespace(
        model_limit_enforcement=SimpleNamespace(enabled=True)
    )
    app_state.get_model_defaults.return_value = {}
    app_state.get_backend_type.return_value = "openai"

    model_catalog = MagicMock()
    model_catalog.get_limits.return_value = None
    model_catalog.get_input_modalities.return_value = {"text"}

    preparer = BackendPreparer(backend_request_manager, app_state, model_catalog)

    request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartImage(
                        image_url=ImageURL(url="data:image/png;base64,AAA", detail=None)
                    )
                ],
            )
        ],
    )
    backend_request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartImage(
                        image_url=ImageURL(url="data:image/png;base64,AAA", detail=None)
                    )
                ],
            )
        ],
    )
    backend_request_manager.prepare_backend_request.return_value = backend_request

    processed = ProcessedResult(
        modified_messages=[], command_executed=False, command_results=[]
    )
    context = RequestContext(headers={}, cookies={}, state=None, app_state=app_state)

    monkeypatch.setattr(
        "src.core.services.backend_preparer.count_tokens", lambda *_args, **_kwargs: 1
    )

    with pytest.raises(InvalidRequestError) as excinfo:
        await preparer.prepare(context, "session_id", request, processed)

    error_dict = excinfo.value.to_dict()
    assert error_dict["error"]["code"] == "unsupported_modality"
