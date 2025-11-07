"""Message augmentation helpers for the hybrid connector."""

from __future__ import annotations

import copy
import logging

logger = logging.getLogger(__name__)


class HybridMessageAugmentationMixin:
    """Logic for injecting reasoning output into conversation history."""

    def _format_reasoning_for_model(self, reasoning_output: str, backend: str) -> str:
        """Format reasoning with model-specific tags."""

        tagged, plain = self._prepare_reasoning_texts(reasoning_output, backend)
        return tagged if plain else ""

    def _inject_as_system_message(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Inject reasoning as system message."""

        messages_copy = copy.deepcopy(messages)
        formatted_reasoning = self._format_reasoning_for_model(
            reasoning_output, execution_backend
        )
        if not formatted_reasoning:
            return messages_copy

        system_content = (
            "Consider this reasoning when formulating your response:\n\n"
            f"{formatted_reasoning}"
        )

        has_system_message = False
        for idx, message in enumerate(messages_copy):
            if isinstance(message, dict) and message.get("role") == "system":
                messages_copy[idx][
                    "content"
                ] = f"{message['content']}\n\n{system_content}"
                has_system_message = True
                break

        if not has_system_message:
            system_message = {"role": "system", "content": system_content}
            messages_copy.insert(0, system_message)

        return messages_copy

    def _inject_to_user_message(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Inject reasoning as prefix to first user message."""

        messages_copy = copy.deepcopy(messages)
        formatted_reasoning = self._format_reasoning_for_model(
            reasoning_output, execution_backend
        )
        if not formatted_reasoning:
            return messages_copy

        for idx, message in enumerate(messages_copy):
            if isinstance(message, dict) and message.get("role") == "user":
                original_content = message.get("content", "")
                messages_copy[idx][
                    "content"
                ] = f"{formatted_reasoning}\n\n{original_content}"
                break

        return messages_copy

    def _augment_messages(
        self, messages: list, reasoning_output: str, execution_backend: str
    ) -> list:
        """Augment messages with reasoning using adaptive placement strategy."""

        if not messages:
            logger.warning("Empty message list provided for augmentation")
            return messages

        if self._supports_system_messages(execution_backend):
            logger.debug("Using system message injection for %s", execution_backend)
            augmented_messages = self._inject_as_system_message(
                messages, reasoning_output, execution_backend
            )
        else:
            logger.debug(
                "Using user message prefix injection for %s", execution_backend
            )
            augmented_messages = self._inject_to_user_message(
                messages, reasoning_output, execution_backend
            )

        if self.config.backends.hybrid_backend_repeat_messages:
            formatted_reasoning = self._format_reasoning_for_model(
                reasoning_output, execution_backend
            )
            if formatted_reasoning:
                augmented_messages.append(
                    {"role": "assistant", "content": formatted_reasoning}
                )

        return augmented_messages
