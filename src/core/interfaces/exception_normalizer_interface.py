"""Interface for exception normalizer.

Responsible for translating provider exceptions to domain-specific errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IExceptionNormalizer(ABC):
    """Service interface for normalizing provider exceptions."""

    @abstractmethod
    def normalize(self, exc: Exception, backend_type: str) -> Exception:
        """Translate provider exception to domain error.

        Translation rules:
        - HTTP 429 -> RateLimitExceededError with message extracted from
          nested detail blocks when possible. Preserves retry-after headers
          and computes reset_at.
        - HTTP 4xx -> InvalidRequestError
        - HTTP 5xx/other -> BackendError

        Never raises; always returns a normalized exception.

        Args:
            exc: The original exception from the provider.
            backend_type: The type of backend that raised the exception.

        Returns:
            A normalized domain exception.
        """
