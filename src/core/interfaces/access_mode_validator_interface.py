"""Interface for access mode validation.

This module defines the protocol for validating access mode configuration
rules during proxy startup.
"""

from __future__ import annotations

import argparse
from abc import abstractmethod
from typing import Protocol

from src.core.config.app_config import AppConfig


class IAccessModeValidator(Protocol):
    """Interface for validating access mode configuration rules.

    Validates that access mode settings (Single User Mode vs Multi User Mode)
    are consistent with other configuration values such as host binding,
    authentication settings, OAuth flags, and notification settings.

    Requirements satisfied:
    - 2.1-2.4: Single User Mode localhost enforcement
    - 4.1-4.3: Single User Mode optional authentication
    - 5.1-5.6: Multi User Mode authentication enforcement
    - 7.1-7.4: Multi User Mode OAuth flag rejection
    - 8.1-8.3: Multi User Mode OAuth auto-replacement rejection
    - 9.1-9.5: Multi User Mode desktop notification rejection
    """

    @abstractmethod
    def validate(self, config: AppConfig, args: argparse.Namespace) -> None:
        """Validate access mode configuration rules.

        Checks all access mode validation rules:
        - Single User Mode requires localhost binding
        - Multi User Mode requires authentication for non-localhost
        - Multi User Mode blocks OAuth debugging override flags
        - Multi User Mode blocks OAuth auto-replacement flag
        - Multi User Mode blocks desktop notifications

        Args:
            config: The application configuration containing access mode settings
            args: Parsed command-line arguments namespace

        Raises:
            ValueError: If validation fails, with detailed error message containing:
                - What validation rule failed
                - Current configuration value that caused the failure
                - Actionable guidance on how to resolve the issue
                - References to relevant CLI flags or configuration options
        """
        ...
