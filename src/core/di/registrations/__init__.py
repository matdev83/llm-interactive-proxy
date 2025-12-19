"""
Feature-scoped DI registration modules.

This package contains registrars for different feature areas, organized to eliminate
the God-Object anti-pattern in the DI registration layer.
"""

from src.core.di.registrations._orchestrator import register_all

__all__ = ["register_all"]
