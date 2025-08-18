"""Inspect FastAPI application state for debugging refactor-related issues.

Run with the project's virtualenv python to print whether key attributes
(`service_provider`, `app_config`, backend-related attrs) exist on app.state.
"""
from __future__ import annotations

from src.core.app.application_factory import build_app


def main() -> None:
    app = build_app()
    sp = getattr(app.state, "service_provider", None)
    conf = getattr(app.state, "app_config", None)

    print(f"service_provider: {bool(sp)}")
    print(f"service_provider repr: {repr(sp)}")

    if conf is None:
        print("app_config: None")
    else:
        print("app_config: present")
        print("  has auth:", hasattr(conf, "auth"))
        if hasattr(conf, "auth"):
            print("  auth.api_keys:", getattr(conf.auth, "api_keys", None))
        print("  default_backend:", getattr(getattr(conf, "backends", None), "default_backend", None))
        print("  functional_backends:", getattr(getattr(conf, "backends", None), "functional_backends", None))

    print("app.state.functional_backends:", getattr(app.state, "functional_backends", None))
    print("app.state.backend_type:", getattr(app.state, "backend_type", None))
    print("app.state.openrouter_backend:", getattr(app.state, "openrouter_backend", None))
    print("app.state.service_provider methods:", None if sp is None else [m for m in dir(sp) if not m.startswith("_")][:20])


if __name__ == "__main__":
    main()




