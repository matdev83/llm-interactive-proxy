"""
Connector mixins for shared functionality across backend connectors.
"""

import warnings

# Suppress deprecation warning for antigravity_auth_mixin as it's intentional and documented
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from src.connectors.mixins.antigravity_auth_mixin import AntigravityAuthMixin

from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin

__all__ = ["GeminiCodeAssistMixin", "AntigravityAuthMixin"]
