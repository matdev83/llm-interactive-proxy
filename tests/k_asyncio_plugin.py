"""Minimal asyncio support plugin for pytest when pytest-asyncio is unavailable."""

from __future__ import annotations

import asyncio
import inspect


def pytest_pyfunc_call(pyfuncitem):  # type: ignore[no-untyped-def]
    test_func = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_func):
        loop = asyncio.new_event_loop()
        try:
            params = inspect.signature(test_func).parameters
            call_kwargs = {name: pyfuncitem.funcargs[name] for name in params}
            loop.run_until_complete(test_func(**call_kwargs))
        finally:
            loop.close()
        return True
    return None
