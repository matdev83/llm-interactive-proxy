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
from typing import Any


def _load_pytest_module() -> ModuleType | None:
    try:
        return importlib.import_module("pytest")
    except ImportError:  # pragma: no cover - pytest not installed in runtime
        return None
    except (AttributeError, ValueError, TypeError) as e:  # pragma: no cover - defensive
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

    original_warns = getattr(pytest_module, "warns", None)
    if original_warns is not None:
        warns_delegate: WarnsCallable = original_warns
        try:  # Check if pytest.warns already supports None
            with pytest_module.warns(None):  # type: ignore[arg-type]
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

            pytest_module.warns = _warns_patch  # type: ignore[attr-defined]

asyncio_logger = logging.getLogger("asyncio")
if asyncio_logger.level == logging.NOTSET:
    asyncio_logger.setLevel(logging.WARNING)

if sys.platform.startswith("win"):
    try:
        windows_events = getattr(asyncio, "windows_events", None)
        if windows_events is None:
            # Windows-specific asyncio extensions not available
            logger = logging.getLogger(__name__)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("asyncio.windows_events not available, skipping event loop policy change")
        else:
            policy = asyncio.get_event_loop_policy()
            if not isinstance(policy, windows_events.WindowsProactorEventLoopPolicy):
                # Already using SelectorEventLoopPolicy or a custom policy
                logger = logging.getLogger(__name__)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Event loop policy is not WindowsProactorEventLoopPolicy (current: %s), skipping",
                        type(policy).__name__,
                    )
            else:
                # Attempt to switch to SelectorEventLoopPolicy to avoid Proactor shutdown hangs
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                logger = logging.getLogger(__name__)
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Switched to WindowsSelectorEventLoopPolicy for improved shutdown behavior")

    except (AttributeError, TypeError) as e:
        # Expected errors from attribute access or type checking
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Expected error accessing asyncio.windows_events or checking policy type: %s",
                e,
                exc_info=True,
            )
    except RuntimeError as e:
        # RuntimeError: event loop policy cannot be changed after loop is created
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Cannot change event loop policy: %s (event loop may already be created)",
                e,
                exc_info=True,
            )
    except Exception as e:
        # Fallback for unexpected errors - log with full traceback for debugging
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.ERROR):
            logger.error(
                "Unexpected error setting WindowsSelectorEventLoopPolicy: %s",
                e,
                exc_info=True,
                extra={"error_code": "EVENT_LOOP_POLICY_SETUP_FAILED"},
            )
