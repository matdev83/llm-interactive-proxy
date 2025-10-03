"""
Stub file to help mypy resolve imports correctly.
This redirects imports from the old path to the new path.
"""

from src.core.interfaces.domain_entities_interface import (
    IEntity,
    ISession,
    ISessionState,
    IValueObject,
)

__all__ = ["IEntity", "ISession", "ISessionState", "IValueObject"]
