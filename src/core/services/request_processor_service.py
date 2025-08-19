from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


"""Re-export the original RequestProcessor implementation.

Some tests expect helper methods on the class; to preserve that shape we
simply import and expose the original implementation rather than wrapping it.
"""

from src.core.services.request_processor import RequestProcessor as _Orig

# Re-export the original class under the expected name
RequestProcessor = _Orig


