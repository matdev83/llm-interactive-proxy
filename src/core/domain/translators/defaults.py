from __future__ import annotations

import weakref

from src.core.domain.translators.registry import TranslatorRegistry
from src.core.interfaces.translator_protocol import TranslatorProtocol

_DEFAULTS_INSTALLED: weakref.WeakSet[TranslatorRegistry] = weakref.WeakSet()


def ensure_default_translator_factories_registered(
    registry: TranslatorRegistry,
) -> None:
    """Register factories for built-in translators if missing.

    This keeps import costs low by avoiding eager imports of translator modules.
    """

    if registry in _DEFAULTS_INSTALLED:
        return

    def _openai_factory() -> TranslatorProtocol:
        from src.core.domain.translators.openai_translator import OpenAITranslator

        return OpenAITranslator()

    def _anthropic_factory() -> TranslatorProtocol:
        from src.core.domain.translators.anthropic_translator import AnthropicTranslator

        return AnthropicTranslator()

    def _gemini_factory() -> TranslatorProtocol:
        from src.core.domain.translators.gemini_translator import GeminiTranslator

        return GeminiTranslator()

    def _responses_factory() -> TranslatorProtocol:
        from src.core.domain.translators.responses_translator import ResponsesTranslator

        return ResponsesTranslator()

    def _code_assist_factory() -> TranslatorProtocol:
        from src.core.domain.translators.code_assist_translator import (
            CodeAssistTranslator,
        )

        return CodeAssistTranslator()

    def _openrouter_factory() -> TranslatorProtocol:
        from src.core.domain.translators.openrouter_translator import (
            OpenRouterTranslator,
        )

        return OpenRouterTranslator()

    def _raw_text_factory() -> TranslatorProtocol:
        from src.core.domain.translators.raw_text_translator import RawTextTranslator

        return RawTextTranslator()

    if not registry.has("openai"):
        registry.register_factory("openai", _openai_factory)

    if not registry.has("anthropic"):
        registry.register_factory("anthropic", _anthropic_factory)

    if not registry.has("gemini"):
        registry.register_factory("gemini", _gemini_factory)

    if not registry.has("responses"):
        registry.register_factory("responses", _responses_factory)

    if not registry.has("code_assist"):
        registry.register_factory("code_assist", _code_assist_factory)

    if not registry.has("openrouter"):
        registry.register_factory("openrouter", _openrouter_factory)

    if not registry.has("raw_text"):
        registry.register_factory("raw_text", _raw_text_factory)

    _DEFAULTS_INSTALLED.add(registry)
