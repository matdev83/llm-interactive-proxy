"""Core package initialization and compatibility shims."""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import warnings
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager as ContextManager
from contextlib import contextmanager
from types import ModuleType
from typing import Any, cast


def _load_pytest_module() -> ModuleType | None:
    try:
        return cast(ModuleType, importlib.import_module("pytest"))
    except ImportError:  # pragma: no cover - pytest not installed in runtime
        return None
    except Exception as e:  # pragma: no cover - defensive
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unexpected error importing pytest module: %s",
                e,
                exc_info=True,
            )
        return None


pytest_module = _load_pytest_module()

if pytest_module is not None:
    WarnsCallable = Callable[..., ContextManager[Any]]
    WarningExpectation = type[Warning] | tuple[type[Warning], ...] | None

    original_warns = cast(WarnsCallable | None, getattr(pytest_module, "warns", None))
    if original_warns is not None:
        warns_delegate: WarnsCallable = original_warns
        try:  # Check if pytest.warns already supports None
            with cast(Any, pytest_module.warns)(None):
                pass
        except TypeError:

            @contextmanager
            def _no_warning_context() -> Iterator[list[warnings.WarningMessage]]:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    yield caught
                    if caught:
                        categories = {record.category.__name__ for record in caught}
                        categories_str = ", ".join(sorted(categories))
                        raise AssertionError(
                            f"Unexpected warnings captured: {categories_str}"
                        )

            def _warns_patch(
                expected_warning: WarningExpectation = None,
                *args: Any,
                **kwargs: Any,
            ) -> ContextManager[Any]:
                if expected_warning is None:
                    return _no_warning_context()
                return warns_delegate(expected_warning, *args, **kwargs)

            cast(Any, pytest_module).warns = _warns_patch

asyncio_logger = logging.getLogger("asyncio")
if asyncio_logger.level == logging.NOTSET:
    asyncio_logger.setLevel(logging.WARNING)

if sys.platform.startswith("win"):
    try:
        windows_events = getattr(asyncio, "windows_events", None)
        policy = asyncio.get_event_loop_policy()
        if windows_events and isinstance(
            policy, windows_events.WindowsProactorEventLoopPolicy
        ):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception as e:
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to set WindowsSelectorEventLoopPolicy: %s",
                e,
                exc_info=True,
            )
