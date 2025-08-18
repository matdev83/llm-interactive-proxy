"""Backward-compatibility shim for `src.core.interfaces.request_processor_interface`.

This module has been renamed to `request_processor_interface.py`. Importing
from the old module path will continue to work but will emit a
DeprecationWarning. Update imports to use the new module path.
"""

from __future__ import annotations

import warnings

from .request_processor_interface import *

warnings.warn(
    "Importing from 'src.core.interfaces.request_processor_interface' is deprecated; "
    "use 'src.core.interfaces.request_processor_interface' instead",
    DeprecationWarning,
)
