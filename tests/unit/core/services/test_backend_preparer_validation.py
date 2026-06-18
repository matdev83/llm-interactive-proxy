import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import InvalidRequestError
from src.core.config.models.misc import ModelRegistryConfig
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    ImageURL,
    MessageContentPartImage,
)
from src.core.domain.model_capabilities import ModelLimits
from src.core.domain.model_catalog_match import (
    ModelCatalogMatchResult,
    ModelCatalogMatchTier,
)
from src.core.domain.model_utils import ModelDefaults
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.services.backend_preparer import BackendPreparer
from src.core.services.model_catalog_service import ModelCatalogService


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
    model_catalog.resolve.return_value = ModelCatalogMatchResult(
        tier=ModelCatalogMatchTier.EXACT,
        limits=ModelLimits(context_window=1000, max_output_tokens=200),
        input_modalities=None,
        resolved_catalog_key="openai/gpt-4",
        catalog_provider_id="openai",
    )

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
    assert error_dict["error"]["type"] == "invalid_request_error"
    assert error_dict["error"]["code"] == "context_length_exceeded"
    assert error_dict["error"]["param"] == "input"


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
    model_catalog.resolve.return_value = ModelCatalogMatchResult(
        tier=ModelCatalogMatchTier.EXACT,
        limits=ModelLimits(context_window=1000, max_output_tokens=200),
        input_modalities=None,
        resolved_catalog_key="openai/gpt-4",
        catalog_provider_id="openai",
    )

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
    model_catalog.resolve.return_value = ModelCatalogMatchResult(
        tier=ModelCatalogMatchTier.EXACT,
        limits=ModelLimits(context_window=128000, max_output_tokens=4096),
        input_modalities=frozenset(["text"]),
        resolved_catalog_key="openai/gpt-4",
        catalog_provider_id="openai",
    )

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


@pytest.mark.asyncio
async def test_backend_preparer_enforces_model_defaults_when_catalog_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_request_manager = MagicMock()
    backend_request_manager.prepare_backend_request = AsyncMock()

    app_state = MagicMock()
    app_state.get_setting.return_value = SimpleNamespace(
        model_limit_enforcement=SimpleNamespace(enabled=True)
    )
    app_state.get_model_defaults.return_value = {
        "gpt-4": {"limits": {"context_window": 1000, "max_output_tokens": 200}}
    }
    app_state.get_backend_type.return_value = "openai"

    model_catalog = MagicMock()
    model_catalog.resolve.return_value = ModelCatalogMatchResult(
        tier=ModelCatalogMatchTier.NONE,
        limits=None,
        input_modalities=None,
        resolved_catalog_key=None,
        catalog_provider_id=None,
    )

    preparer = BackendPreparer(backend_request_manager, app_state, model_catalog)

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
        "src.core.services.backend_preparer.count_tokens",
        lambda *_args, **_kwargs: 9999,
    )

    with pytest.raises(InvalidRequestError) as exc:
        await preparer.prepare(context, "session_id", request, processed)

    err = exc.value.to_dict()["error"]
    assert exc.value.status_code == 400
    assert err["type"] == "invalid_request_error"
    assert err["code"] == "context_length_exceeded"
    assert err["details"]["limit"] == 1000


def _real_catalog_service(limits: dict) -> tuple[ModelCatalogService, str]:
    mock_data = {"openai": {"models": {"gpt-4": {"limit": limits}}}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(mock_data, f)
        temp_path = f.name
    config = ModelRegistryConfig(bootstrap_path=temp_path, cache_path=temp_path)
    return ModelCatalogService(config), temp_path


@pytest.mark.asyncio
async def test_backend_preparer_enforces_input_limit_via_real_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration: models.dev limits drive canonical context overflow rejection."""
    catalog, path = _real_catalog_service({"context": 500, "output": 100})
    try:
        backend_request_manager = MagicMock()
        backend_request_manager.prepare_backend_request = AsyncMock()
        app_state = MagicMock()
        app_state.get_setting.return_value = SimpleNamespace(
            model_limit_enforcement=SimpleNamespace(enabled=True)
        )
        app_state.get_model_defaults.return_value = {}
        app_state.get_backend_type.return_value = "openai"
        preparer = BackendPreparer(backend_request_manager, app_state, catalog)
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
        context = RequestContext(
            headers={}, cookies={}, state=None, app_state=app_state
        )
        monkeypatch.setattr(
            "src.core.services.backend_preparer.count_tokens",
            lambda *_a, **_k: 600,
        )
        with pytest.raises(InvalidRequestError) as exc:
            await preparer.prepare(context, "session_id", request, processed)
        err = exc.value.to_dict()["error"]
        assert exc.value.status_code == 400
        assert err["type"] == "invalid_request_error"
        assert err["code"] == "context_length_exceeded"
        assert err["param"] == "input"
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_backend_preparer_model_defaults_override_catalog_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_defaults limits win; catalog would allow more input."""
    catalog, path = _real_catalog_service({"context": 100000, "output": 8192})
    try:
        backend_request_manager = MagicMock()
        backend_request_manager.prepare_backend_request = AsyncMock()
        app_state = MagicMock()
        app_state.get_setting.return_value = SimpleNamespace(
            model_limit_enforcement=SimpleNamespace(enabled=True)
        )
        app_state.get_model_defaults.return_value = {
            "gpt-4": ModelDefaults.model_validate(
                {"limits": ModelLimits(context_window=400, max_output_tokens=50)}
            )
        }
        app_state.get_backend_type.return_value = "openai"
        preparer = BackendPreparer(backend_request_manager, app_state, catalog)
        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="x")]
        )
        backend_request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="x")]
        )
        backend_request_manager.prepare_backend_request.return_value = backend_request
        processed = ProcessedResult(
            modified_messages=[], command_executed=False, command_results=[]
        )
        context = RequestContext(
            headers={}, cookies={}, state=None, app_state=app_state
        )
        monkeypatch.setattr(
            "src.core.services.backend_preparer.count_tokens",
            lambda *_a, **_k: 500,
        )
        with pytest.raises(InvalidRequestError) as exc:
            await preparer.prepare(context, "session_id", request, processed)
        err = exc.value.to_dict()["error"]
        assert err["type"] == "invalid_request_error"
        assert err["code"] == "context_length_exceeded"
        assert err["param"] == "input"
        assert err["details"]["limit"] == 400
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_backend_preparer_enforcement_disabled_skips_catalog_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model_limit_enforcement.enabled is False, no 413 even if input exceeds catalog."""
    catalog, path = _real_catalog_service({"context": 10, "output": 5})
    try:
        backend_request_manager = MagicMock()
        backend_request_manager.prepare_backend_request = AsyncMock()
        app_state = MagicMock()
        app_state.get_setting.return_value = SimpleNamespace(
            model_limit_enforcement=SimpleNamespace(enabled=False)
        )
        app_state.get_model_defaults.return_value = {}
        app_state.get_backend_type.return_value = "openai"
        preparer = BackendPreparer(backend_request_manager, app_state, catalog)
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
        context = RequestContext(
            headers={}, cookies={}, state=None, app_state=app_state
        )
        monkeypatch.setattr(
            "src.core.services.backend_preparer.count_tokens",
            lambda *_a, **_k: 99999,
        )
        result = await preparer.prepare(context, "session_id", request, processed)
        assert result is not None
    finally:
        Path(path).unlink(missing_ok=True)
