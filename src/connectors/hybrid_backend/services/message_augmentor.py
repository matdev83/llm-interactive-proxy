"""MessageAugmentor service for injecting reasoning into message lists.

This service extracts message augmentation logic from HybridConnector to provide
focused, testable components for injecting reasoning into message lists.

Requirements satisfied:
- Req 2.3: MessageAugmentor extraction
- Req 3: Protocol-first design
"""

import copy
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.connectors.hybrid_backend.protocols import IReasoningMarkupProcessor
    from src.core.config.app_config import AppConfig

from src.connectors.hybrid_backend.protocols import (
    IReasoningMarkupProcessor,
)
from src.connectors.utils.model_capabilities import supports_system_messages
from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


class MessageAugmentor:
    """Service for injecting reasoning into message lists.

    Handles adaptive placement of reasoning content based on backend capabilities:
    - System message injection (if backend supports system role)
    - User message prepending (fallback strategy)
    - Repeat-message mode (assistant message injection)
    """

    def __init__(
        self,
        markup_processor: IReasoningMarkupProcessor,
        config: AppConfig,
    ) -> None:
        """Initialize MessageAugmentor.

        Args:
            markup_processor: Processor for formatting reasoning tags
            config: Application configuration
        """
        self._markup_processor = markup_processor
        self._config = config

    def _inject_as_system_message(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Inject reasoning as system message.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name for tag formatting

        Returns:
            Messages with reasoning in system message
        """
        # Format reasoning with appropriate tags first to avoid copying if not needed
        formatted_reasoning = self._markup_processor.format_for_model(
            reasoning_output, execution_backend
        )
        if not formatted_reasoning:
            # Return shallow copy since we're not modifying anything
            return list(messages)

        # Create system message content
        system_content = (
            "Consider this reasoning when formulating your response:\n\n"
            f"{formatted_reasoning}"
        )

        # Shallow copy the list - we'll only deepcopy the specific message we modify
        messages_copy = list(messages)

        # Check if there's already a system message
        for i, msg in enumerate(messages_copy):
            if isinstance(msg, dict) and msg.get("role") == "system":
                # Augment existing system message - deepcopy only this message
                modified_msg = copy.deepcopy(msg)
                modified_msg["content"] = f"{msg['content']}\n\n{system_content}"
                messages_copy[i] = modified_msg
                return messages_copy

        # If no system message exists, create one at the beginning
        system_message = {"role": "system", "content": system_content}
        messages_copy.insert(0, system_message)

        return messages_copy

    def _inject_to_user_message(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Inject reasoning as prefix to first user message.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name for tag formatting

        Returns:
            Messages with reasoning prepended to first user message
        """
        # Format reasoning with appropriate tags first to avoid copying if not needed
        formatted_reasoning = self._markup_processor.format_for_model(
            reasoning_output, execution_backend
        )
        if not formatted_reasoning:
            # Return shallow copy since we're not modifying anything
            return list(messages)

        # Shallow copy the list - we'll only deepcopy the specific message we modify
        messages_copy = list(messages)

        # Find first user message
        for i, msg in enumerate(messages_copy):
            if isinstance(msg, dict) and msg.get("role") == "user":
                # Prepend reasoning to user message - deepcopy only this message
                modified_msg = copy.deepcopy(msg)
                original_content = msg.get("content", "")
                modified_msg["content"] = f"{formatted_reasoning}\n\n{original_content}"
                messages_copy[i] = modified_msg
                break

        return messages_copy

    def augment(
        self,
        messages: list[Any],
        reasoning_output: str,
        execution_backend: str,
    ) -> list[Any]:
        """Inject reasoning into messages using appropriate strategy.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name to determine injection strategy

        Returns:
            New message list with reasoning injected appropriately.
            Strategy depends on backend capabilities:
            - System message injection if backend supports system role
            - User message prepending otherwise
        """
        # Handle edge case: empty messages
        if not messages:
            logger.warning("Empty message list provided for augmentation")
            return messages

        # Check if execution backend supports system messages
        if supports_system_messages(execution_backend):
            # Primary strategy: inject as system message
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Using system message injection for {execution_backend}")
            augmented_messages = self._inject_as_system_message(
                messages, reasoning_output, execution_backend
            )
        else:
            # Fallback strategy: inject to user message
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Using user message prefix injection for {execution_backend}"
                )
            augmented_messages = self._inject_to_user_message(
                messages, reasoning_output, execution_backend
            )

        # Handle repeat-messages mode
        if self._config.backends.hybrid_backend_repeat_messages:
            formatted_reasoning = self._markup_processor.format_for_model(
                reasoning_output, execution_backend
            )
            if formatted_reasoning:
                plain_reasoning = self._markup_processor.extract_plain_text(
                    formatted_reasoning
                )
                augmented_messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "reasoning": formatted_reasoning,
                        "reasoning_content": plain_reasoning,
                    }
                )
        return augmented_messages
