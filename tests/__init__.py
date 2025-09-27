# This file makes tests a Python package

# Install narrowly targeted warning filters for known upstream/library warnings.
# Applied identically across platforms; project-owned warnings are fixed at source.
import warnings as _warnings

# websockets 12+ deprecates websockets.legacy; triggered by upstream SDKs
_warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*websockets\.legacy is deprecated.*",
)

# execnet/xdist on Windows may emit a spurious unclosed ProactorEventLoop warning
_warnings.filterwarnings(
    "ignore",
    category=ResourceWarning,
    message=r"unclosed event loop <ProactorEventLoop.*",
)

# websockets.server.WebSocketServerProtocol deprecation via uvicorn websockets_impl
_warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*websockets\.server\.WebSocketServerProtocol is deprecated.*",
)

# importlib.metadata EntryPoints dict deprecation from plugins/importlib
_warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*Construction of dict of EntryPoints is deprecated.*",
)

# Occasional unclosed file warnings from pytest internals on Windows
_warnings.filterwarnings(
    "ignore",
    category=ResourceWarning,
    message=r"unclosed file <_io\..*",
)
