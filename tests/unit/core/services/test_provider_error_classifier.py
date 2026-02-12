"""Unit tests for provider error classification contract."""

from __future__ import annotations

from fastapi import HTTPException
from src.core.interfaces.provider_error_classifier_interface import (
    IProviderErrorClassifier,
)
from src.core.services.provider_error_classifier import ProviderErrorClassifier


class TestProviderErrorClassifier:
    def test_classifier_implements_interface(self) -> None:
        classifier = ProviderErrorClassifier()

        assert isinstance(classifier, IProviderErrorClassifier)

    def test_model_not_found_is_classified_as_unsupported_on_instance(self) -> None:
        classifier = ProviderErrorClassifier()
        exc = HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": "The model gpt-4.1-mini was not found",
                    "code": "model_not_found",
                }
            },
        )

        result = classifier.classify(exc)

        assert result.code == "unsupported_on_instance"
        assert result.category == "availability"
        assert result.retryable is False

    def test_rate_limit_is_classified_as_temporarily_unavailable(self) -> None:
        classifier = ProviderErrorClassifier()
        exc = HTTPException(status_code=429, detail={"message": "Rate limit exceeded"})

        result = classifier.classify(exc)

        assert result.code == "temporarily_unavailable"
        assert result.category == "availability"
        assert result.retryable is True

    def test_model_not_found_has_precedence_over_retryable_signals(self) -> None:
        classifier = ProviderErrorClassifier()
        exc = HTTPException(
            status_code=429,
            detail={
                "error": {
                    "message": "Model not found for this project",
                    "code": "model_not_found",
                }
            },
        )

        result = classifier.classify(exc)

        assert result.code == "unsupported_on_instance"
        assert result.retryable is False
