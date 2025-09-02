from dataclasses import dataclass
from enum import Enum, auto

from src.core.common.exceptions import ConfigurationError


class ReplacementMode(Enum):
    """Enum for replacement modes."""

    REPLACE = auto()
    PREPEND = auto()
    APPEND = auto()


@dataclass
class ReplacementRule:
    """Data model for a single replacement rule."""

    mode: ReplacementMode
    search: str | None = None
    replace: str | None = None
    prepend: str | None = None
    append: str | None = None

    def __post_init__(self) -> None:
        """Validate the replacement rule."""
        if self.mode == ReplacementMode.REPLACE:
            if self.search is None or self.replace is None:
                raise ConfigurationError(
                    "'search' and 'replace' must be set for REPLACE mode."
                )
            if self.prepend is not None or self.append is not None:
                raise ConfigurationError(
                    "'prepend' and 'append' must not be set for REPLACE mode."
                )
        elif self.mode == ReplacementMode.PREPEND:
            if self.search is None or self.prepend is None:
                raise ConfigurationError(
                    "'search' and 'prepend' must be set for PREPEND mode."
                )
            if self.replace is not None or self.append is not None:
                raise ConfigurationError(
                    "'replace' and 'append' must not be set for PREPEND mode."
                )
        elif self.mode == ReplacementMode.APPEND:
            if self.search is None or self.append is None:
                raise ConfigurationError(
                    "'search' and 'append' must be set for APPEND mode."
                )
            if self.replace is not None or self.prepend is not None:
                raise ConfigurationError(
                    "'replace' and 'prepend' must not be set for APPEND mode."
                )
