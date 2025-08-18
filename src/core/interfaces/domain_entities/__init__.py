"""
Stub file to help mypy resolve imports correctly.
This redirects imports from the old path to the new path.
"""

from src.core.interfaces.domain_entities_interface import IValueObject, IEntity, ISession, ISessionState

__all__ = ["IValueObject", "IEntity", "ISession", "ISessionState"]
