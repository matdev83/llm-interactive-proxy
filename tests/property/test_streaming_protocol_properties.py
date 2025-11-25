from __future__ import annotations

import importlib
import inspect

CONNECTOR_CLASSES = [
    ("src.connectors.openai", "OpenAIConnector"),
    ("src.connectors.anthropic", "AnthropicBackend"),
    ("src.connectors.gemini", "GeminiBackend"),
]


def test_property_5_stream_producer_protocol() -> None:
    """
    Property 5: StreamProducer protocol conformance.

    Every streaming connector must implement stream_completion and
    get_provider_name to satisfy the StreamProducer protocol.
    """

    for module_name, class_name in CONNECTOR_CLASSES:
        module = importlib.import_module(module_name)
        connector_cls = getattr(module, class_name)
        stream_completion = getattr(connector_cls, "stream_completion", None)
        provider_name = getattr(connector_cls, "get_provider_name", None)
        assert callable(stream_completion), f"{class_name} missing stream_completion"
        assert callable(provider_name), f"{class_name} missing get_provider_name"
        unwrapped = inspect.unwrap(stream_completion)
        assert inspect.iscoroutinefunction(unwrapped) or inspect.isasyncgenfunction(
            unwrapped
        ), f"{class_name} missing async stream_completion"
