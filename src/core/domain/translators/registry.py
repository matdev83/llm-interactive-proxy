from __future__ import annotations

from collections.abc import Callable, Mapping

from src.core.interfaces.translator_protocol import TranslatorProtocol


class TranslatorRegistry:
    """Registry for managing translator instances."""

    def __init__(self, *, aliases: Mapping[str, str] | None = None) -> None:
        self._aliases = {
            (key.strip().lower()): value.strip().lower()
            for key, value in (aliases or _DEFAULT_FORMAT_ALIASES).items()
        }
        self._translators: dict[str, TranslatorProtocol] = {}
        self._factories: dict[str, Callable[[], TranslatorProtocol]] = {}

    def register(self, translator: TranslatorProtocol) -> None:
        """Register a translator instance for all of its supported format keys."""
        if not isinstance(translator, TranslatorProtocol):
            raise TypeError("Translator must implement TranslatorProtocol")

        for format_name in translator.format_names:
            if not isinstance(format_name, str) or not format_name.strip():
                raise ValueError("Translator format name must be a non-empty string")
            self._translators[self._normalize_format_name(format_name)] = translator

    def register_factory(
        self, format_name: str, factory: Callable[[], TranslatorProtocol]
    ) -> None:
        """Register a factory for lazy translator creation."""
        if not isinstance(format_name, str) or not format_name.strip():
            raise ValueError("Factory format name must be a non-empty string")
        self._factories[self._normalize_format_name(format_name)] = factory

    def get(self, format_name: str) -> TranslatorProtocol:
        """Get translator by format name, creating if necessary."""
        normalized = self._normalize_format_name(format_name)

        translator = self._translators.get(normalized)
        if translator is not None:
            return translator

        factory = self._factories.get(normalized)
        if factory is None:
            raise KeyError(f"No translator registered for format: {format_name}")

        translator = factory()
        self.register(translator)
        return translator

    def has(self, format_name: str) -> bool:
        """Check if a translator is registered for the format."""
        normalized = self._normalize_format_name(format_name)
        return normalized in self._translators or normalized in self._factories

    def _normalize_format_name(self, format_name: str) -> str:
        key = format_name.strip().lower()
        return self._aliases.get(key, key)


_DEFAULT_FORMAT_ALIASES: Mapping[str, str] = {
    "openai-responses": "responses",
}

_global_registry = TranslatorRegistry()


def get_global_translator_registry() -> TranslatorRegistry:
    """Return the process-wide translator registry used by Translation and TranslationService."""

    return _global_registry
