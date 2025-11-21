from unittest.mock import MagicMock

from src.connectors.hybrid import HybridConnector
from src.core.config.app_config import AppConfig


def _connector_with_repeat(repeat: bool) -> HybridConnector:
    config = AppConfig()
    config.backends.hybrid_backend_repeat_messages = repeat
    return HybridConnector(
        client=MagicMock(),
        config=config,
        translation_service=MagicMock(),
        backend_registry=MagicMock(),
    )


def test_augment_injects_reasoning_into_system_message() -> None:
    connector = _connector_with_repeat(repeat=False)
    base_messages = [{"role": "user", "content": "Hi"}]

    augmented = connector._augment_messages(
        messages=base_messages,
        reasoning_output="Think about this",
        execution_backend="zenmux",
    )

    assert augmented[0]["role"] == "system"
    assert "Think about this" in augmented[0]["content"]
    assert augmented[1]["role"] == "user"


def test_augment_appends_reasoning_message_without_content_when_repeat_enabled() -> (
    None
):
    connector = _connector_with_repeat(repeat=True)
    base_messages = [{"role": "user", "content": "Hello"}]

    augmented = connector._augment_messages(
        messages=base_messages,
        reasoning_output="Plan the steps",
        execution_backend="zenmux",
    )

    assert augmented[-1]["role"] == "assistant"
    assert augmented[-1]["content"] == ""
    assert augmented[-1]["reasoning_content"] == "Plan the steps"
