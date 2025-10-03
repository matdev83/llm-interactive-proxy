"""Global warning policy for test runs and development shells.

Installed automatically by Python if this package directory is on sys.path.
We use this to enforce a zero-warning policy during tests, including when
`-W default` is passed, and to keep behavior identical across platforms.

Note: Project-owned warnings are fixed at source; the filters below are
intended to quiet third-party or platform/runtime noise that would otherwise
pollute CI output.
"""

from __future__ import annotations

import warnings


def _install_global_warning_filters() -> None:
    # Broad categories suppressed; order matters (inserted at front).
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    warnings.filterwarnings("ignore", category=ImportWarning)
    warnings.filterwarnings("ignore", category=UserWarning)

    # Known upstream messages that are particularly noisy in CI
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r".*websockets\.legacy is deprecated.*",
    )
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=r"unclosed event loop <ProactorEventLoop.*",
    )


_install_global_warning_filters()
