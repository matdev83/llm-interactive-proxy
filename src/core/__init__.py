"""Core package public surface.

This package intentionally keeps lightweight exports for the most commonly used
types (such as :class:`AppConfig`), while the CLI entrypoint lives in
`src/core/cli.py`.

The legacy `src.core.cli_v2` module is consolidated into the canonical CLI
implementation. To avoid keeping two separate source files while still
supporting existing import paths, we register a small in-memory compatibility
module under `src.core.cli_v2` that delegates to `src.core.cli`.
"""

from __future__ import annotations

from .config.app_config import AppConfig, LogLevel

__all__ = ["AppConfig", "LogLevel"]


def _install_cli_v2_compat() -> None:
    import importlib.abc
    import importlib.machinery
    import os
    import sys
    import types
    from collections.abc import Callable
    from typing import Any, Protocol, cast

    module_name = f"{__name__}.cli_v2"
    if module_name in sys.modules:
        return

    compat_module: Any = types.ModuleType(module_name)
    compat_module.__doc__ = (
        "Compatibility layer exposing the legacy :mod:`src.core.cli_v2` API.\n\n"
        "Historically the proxy shipped a ``cli_v2`` module while the staged CLI\n"
        "implementation was being validated. The canonical implementation now lives in\n"
        ":mod:`src.core.cli`, but some tooling and documentation in the wider ecosystem\n"
        "may still reference the old module path.\n\n"
        "This compatibility module is provided in-memory to avoid maintaining two\n"
        "separate source files while still supporting the old import path."
    )
    compat_module.__all__ = [
        "AppConfig",
        "apply_cli_args",
        "is_port_in_use",
        "main",
        "parse_cli_args",
    ]

    class _CliModuleApi(Protocol):
        def parse_cli_args(self, argv: list[str] | None = None) -> Any: ...

        def apply_cli_args(self, args: Any) -> Any: ...

        def is_port_in_use(self, host: str, port: int) -> bool: ...

        def main(
            self,
            *,
            argv: list[str] | None = None,
            build_app_fn: Callable[[AppConfig], Any] | None = None,
        ) -> Any: ...

    class _CliModuleProxy:
        def __init__(self) -> None:
            self._module: _CliModuleApi | None = None

        def _load(self) -> _CliModuleApi:
            if self._module is None:
                from src.core import cli as cli_module

                self._module = cast(_CliModuleApi, cli_module)
            return self._module

        def parse_cli_args(self, argv: list[str] | None = None) -> Any:
            return self._load().parse_cli_args(argv)

        def apply_cli_args(self, args: Any) -> Any:
            return self._load().apply_cli_args(args)

        def is_port_in_use(self, host: str, port: int) -> bool:
            return self._load().is_port_in_use(host, port)

        def main(
            self,
            *,
            argv: list[str] | None = None,
            build_app_fn: Callable[[AppConfig], Any] | None = None,
        ) -> Any:
            return self._load().main(argv=argv, build_app_fn=build_app_fn)

    compat_module._cli_module = _CliModuleProxy()

    compat_module.AppConfig = AppConfig

    class _CliV2CompatLoader(importlib.abc.Loader):
        def create_module(self, spec: importlib.machinery.ModuleSpec) -> Any:
            return compat_module

        def exec_module(self, module: types.ModuleType) -> None:
            return

        def get_code(self, fullname: str) -> Any:
            source = (
                "from src.core.cli import main as _main\n"
                "import asyncio\n"
                "asyncio.run(_main())\n"
            )
            return compile(source, "<src.core.cli_v2>", "exec")

    compat_module.__file__ = "<in-memory src.core.cli_v2>"

    loader = _CliV2CompatLoader()
    compat_module.__spec__ = importlib.machinery.ModuleSpec(
        module_name,
        loader,
        origin=compat_module.__file__,
        is_package=False,
    )
    compat_module.__loader__ = loader
    compat_module.__package__ = __name__

    def parse_cli_args(argv: list[str] | None = None) -> Any:
        return compat_module._cli_module.parse_cli_args(argv)

    def apply_cli_args(args: Any) -> AppConfig:
        result = compat_module._cli_module.apply_cli_args(args)
        config = cast(AppConfig, result[0] if isinstance(result, tuple) else result)
        volatile_env = [
            "PROXY_PORT",
            "COMMAND_PREFIX",
            "FORCE_CONTEXT_WINDOW",
        ]
        for key in volatile_env:
            if key in os.environ and key != "THINKING_BUDGET":
                os.environ.pop(key, None)
        return config

    def is_port_in_use(host: str, port: int) -> bool:
        return bool(compat_module._cli_module.is_port_in_use(host, port))

    def main(
        argv: list[str] | None = None,
        build_app_fn: Callable[[AppConfig], Any] | None = None,
    ) -> None:
        import asyncio
        import inspect

        result = compat_module._cli_module.main(
            argv=argv,
            build_app_fn=build_app_fn,
        )
        if inspect.iscoroutine(result):
            asyncio.run(result)

    compat_module.parse_cli_args = parse_cli_args
    compat_module.apply_cli_args = apply_cli_args
    compat_module.is_port_in_use = is_port_in_use
    compat_module.main = main

    sys.modules[module_name] = compat_module


_install_cli_v2_compat()
