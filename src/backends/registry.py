from __future__ import annotations

from typing import Dict, Tuple

from .base import Backend

_backends: Dict[str, Backend] = {}

def register_backend(backend: Backend) -> None:
    _backends[backend.prefix] = backend

def get_backend(prefix: str) -> Backend | None:
    return _backends.get(prefix)

def select_backend(model: str) -> Tuple[Backend, str]:
    if ':' in model:
        prefix, real_model = model.split(':', 1)
        backend = get_backend(prefix)
        if backend is not None:
            return backend, real_model
    # default backend is first registered
    default_backend = next(iter(_backends.values()))
    return default_backend, model
