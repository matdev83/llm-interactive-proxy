from __future__ import annotations

"""
Compatibility shim: re-export backend service interface from the canonical module.

This preserves existing import paths (tests and code) while consolidating
the actual interface definition in `backend_service.py`.
"""

from src.core.common.exceptions import BackendError  # noqa: F401
from src.core.interfaces.backend_service import IBackendService  # noqa: F401
