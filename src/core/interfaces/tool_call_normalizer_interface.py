"""Interface for normalizing tool-call objects into consistent internal form.

This module defines the contract for components that normalize tool-call objects
from various representations (dicts, Pydantic models, dataclasses) into a
consistent dictionary format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IToolCallNormalizer(ABC):
    """Interface for normalizing tool-call objects to dictionary format.

    This interface defines the contract for components that normalize tool-call
    objects from various representations into a consistent dictionary format.
    Supported input types:
    - Dictionary objects (already normalized)
    - Pydantic models (using `model_dump()`)
    - Dataclass instances (using `asdict()`)

    The normalizer follows a fail-open strategy: un-normalizable objects are
    skipped (returns None) without crashing the request.
    """

    @abstractmethod
    def normalize(self, tool_call: Any) -> dict[str, Any] | None:
        """Normalize a tool-call object into a dictionary.

        This method attempts to normalize a tool-call object into a consistent
        dictionary format. It supports:
        - Dictionary objects: returned as-is
        - Pydantic models: converted using `model_dump()`
        - Dataclass instances: converted using `asdict()`

        Args:
            tool_call: The tool-call object to normalize. Can be a dict,
                Pydantic model, dataclass, or any other object.

        Returns:
            Normalized dictionary representation of the tool call, or None
            if the object cannot be normalized (fail-open behavior).

        Note:
            This method should not raise exceptions. If normalization fails,
            it should return None and log at DEBUG level if needed.
        """
        ...
