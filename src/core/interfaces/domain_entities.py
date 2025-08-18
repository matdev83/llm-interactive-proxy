"""Backward-compatibility shim for `src.core.interfaces.domain_entities`.

Renamed to `domain_entities_interface.py`; import from the new module.
"""

from __future__ import annotations

import warnings

from .domain_entities_interface import *

warnings.warn(
    "Importing from 'src.core.interfaces.domain_entities' is deprecated; "
    "use 'src.core.interfaces.domain_entities_interface' instead",
    DeprecationWarning,
)

