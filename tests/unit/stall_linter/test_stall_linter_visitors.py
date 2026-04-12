from __future__ import annotations

import ast
from pathlib import Path

from tests.unit.stall_linter.engine import (
    _AsyncioSleepWithoutAwaitVisitor,
    _AsyncTaskLeakVisitor,
    _build_stall_lint_suppressions,
    _FakeClockContextSleepVisitor,
    _is_suppressed,
    _PatchRecursionVisitor,
    _RunUntilCompleteInAsyncVisitor,
    _ThreadJoinTimeoutVisitor,
    _ThreadLockAwaitVisitor,
    _WatchdogShutdownVisitor,
)


def test_stall_linter_suppression_mechanism(tmp_path: Path) -> None:
    sample = """\
import asyncio
from unittest.mock import patch


def test_example():
    # stall-lint: ignore=STALL002
    patch("asyncio.sleep", side_effect=lambda *_a, **_kw: asyncio.sleep(0))
"""
    file_path = tmp_path / "sample_test.py"
    file_path.write_text(sample, encoding="utf-8")

    suppressions = _build_stall_lint_suppressions(sample)
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _PatchRecursionVisitor(file_path=file_path)
    visitor.visit(tree)

    unsuppressed = visitor.findings
    assert [f.rule for f in unsuppressed] == ["STALL002"]

    suppressed = [
        finding
        for finding in visitor.findings
        if not _is_suppressed(finding, suppressions)
    ]
    assert suppressed == []


def test_stall_linter_detects_forbidden_recursive_patch(tmp_path: Path) -> None:
    sample = """\
import asyncio
from unittest.mock import patch


def test_example():
    patch("asyncio.sleep", return_value=asyncio.sleep(0))
"""
    file_path = tmp_path / "sample_test.py"
    file_path.write_text(sample, encoding="utf-8")

    suppressions = _build_stall_lint_suppressions(sample)
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _PatchRecursionVisitor(file_path=file_path)
    visitor.visit(tree)

    assert [f.rule for f in visitor.findings] == ["STALL001"]
    assert not _is_suppressed(visitor.findings[0], suppressions)


def test_stall_linter_detects_short_join_without_is_alive(tmp_path: Path) -> None:
    sample = """\
from watchdog.observers import Observer


class SomethingWatcher:
    def __init__(self):
        self._observer = Observer()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=1.0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL010" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_thread_join_timeout_without_check(
    tmp_path: Path,
) -> None:
    sample = """\
import threading


def test_example():
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join(timeout=1.0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _ThreadJoinTimeoutVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL040" in {finding.rule for finding in visitor.findings}


def test_stall_linter_allows_thread_join_timeout_with_is_alive_check(
    tmp_path: Path,
) -> None:
    sample = """\
import threading


def test_example():
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _ThreadJoinTimeoutVisitor(file_path=file_path)
    visitor.visit(tree)
    assert visitor.findings == []


def test_stall_linter_allows_thread_join_timeout_with_daemon(
    tmp_path: Path,
) -> None:
    sample = """\
import threading


def test_example():
    thread = threading.Thread(target=lambda: None, daemon=True)
    thread.start()
    thread.join(timeout=1.0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _ThreadJoinTimeoutVisitor(file_path=file_path)
    visitor.visit(tree)
    assert visitor.findings == []


def test_stall_linter_detects_shutdown_order_issue(tmp_path: Path) -> None:
    sample = """\
class Manager:
    def __init__(self):
        self._watcher = None

    async def shutdown(self):
        self._watcher.stop()
        await self._watcher.cancel_pending_reload()
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL011" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_missing_shutdown_guard(tmp_path: Path) -> None:
    sample = """\
from watchdog.observers import Observer


class CredentialWatcher:
    def __init__(self):
        self._observer = Observer()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5.0)
        if self._observer.is_alive():
            pass

    def schedule_reload(self):
        return
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL012" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_lock_await_deadlock_pattern(tmp_path: Path) -> None:
    sample = """\
import asyncio
import threading


class CredentialWatcher:
    def __init__(self):
        self._reload_task_lock = threading.Lock()
        self._pending_reload_task: asyncio.Future | None = None

    async def cancel_pending_reload(self):
        with self._reload_task_lock:
            if self._pending_reload_task is not None:
                await self._pending_reload_task
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _WatchdogShutdownVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL013" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_fake_clock_sleep_hang(tmp_path: Path) -> None:
    sample = """\
import asyncio
from tests.utils.fake_clock import FakeClockContext


async def test_example():
    async with FakeClockContext():
        await asyncio.sleep(0.01)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _FakeClockContextSleepVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL020" in {finding.rule for finding in visitor.findings}


def test_stall_linter_allows_fake_clock_zero_sleep(tmp_path: Path) -> None:
    sample = """\
import asyncio
from tests.utils.fake_clock import FakeClockContext


async def test_example():
    async with FakeClockContext():
        await asyncio.sleep(0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _FakeClockContextSleepVisitor(file_path=file_path)
    visitor.visit(tree)
    assert visitor.findings == []


def test_stall_linter_allows_sleep_in_nested_task_inside_fake_clock(
    tmp_path: Path,
) -> None:
    sample = """\
import asyncio
from tests.utils.fake_clock import FakeClockContext


async def test_example():
    async with FakeClockContext() as clock:
        async def worker():
            await asyncio.sleep(0.01)

        task = asyncio.create_task(worker())
        clock.advance(0.01)
        await task
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _FakeClockContextSleepVisitor(file_path=file_path)
    visitor.visit(tree)
    assert visitor.findings == []


def test_stall_linter_detects_bare_asyncio_sleep_in_async_fn(
    tmp_path: Path,
) -> None:
    sample = """\
import asyncio


async def test_example():
    asyncio.sleep(0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _AsyncioSleepWithoutAwaitVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL030" in {finding.rule for finding in visitor.findings}


def test_stall_linter_allows_awaited_asyncio_sleep_in_async_fn(
    tmp_path: Path,
) -> None:
    sample = """\
import asyncio


async def test_example():
    await asyncio.sleep(0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _AsyncioSleepWithoutAwaitVisitor(file_path=file_path)
    visitor.visit(tree)
    assert visitor.findings == []


def test_stall_linter_detects_fire_and_forget_task(tmp_path: Path) -> None:
    sample = """\
import asyncio


async def test_example():
    asyncio.create_task(asyncio.sleep(0))
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _AsyncTaskLeakVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL032" in {finding.rule for finding in visitor.findings}


def test_stall_linter_allows_awaited_task_assignment(tmp_path: Path) -> None:
    sample = """\
import asyncio


async def test_example():
    task = asyncio.create_task(asyncio.sleep(0))
    await task
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _AsyncTaskLeakVisitor(file_path=file_path)
    visitor.visit(tree)
    assert visitor.findings == []


def test_stall_linter_detects_run_until_complete_in_async(tmp_path: Path) -> None:
    sample = """\
import asyncio


async def test_example():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0))
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _RunUntilCompleteInAsyncVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL033" in {finding.rule for finding in visitor.findings}


def test_stall_linter_detects_thread_lock_await(tmp_path: Path) -> None:
    sample = """\
import asyncio
import threading


async def test_example():
    lock = threading.Lock()
    with lock:
        await asyncio.sleep(0)
"""
    file_path = tmp_path / "sample.py"
    tree = ast.parse(sample, filename=str(file_path))
    visitor = _ThreadLockAwaitVisitor(file_path=file_path)
    visitor.visit(tree)
    assert "STALL031" in {finding.rule for finding in visitor.findings}
