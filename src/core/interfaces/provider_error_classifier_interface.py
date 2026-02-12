"""Interface for provider error classification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderErrorClassification:
    """Canonical classification payload used by routing/resilience flows."""

    code: str
    category: str
    retryable: bool
    reason: str


class IProviderErrorClassifier(ABC):
    """Service interface for provider-specific error normalization."""

    @abstractmethod
    def classify(self, error: Exception) -> ProviderErrorClassification:
        """Classify provider error into canonical routing categories."""
