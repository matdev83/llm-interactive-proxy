from __future__ import annotations

import threading
from typing import Any, cast

from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState


def test_file_watcher_stop_does_not_join_observer_thread() -> None:
    """Regression: stopping from watchdog thread must not join() itself.

    Historically this raised `RuntimeError: cannot join current thread`, which could
    leave xdist workers in a bad shutdown state.
    """

    state = FileWatcherState()
    done = threading.Event()
    stop_called = threading.Event()
    caught: Exception | None = None

    class FakeObserver(threading.Thread):
        def __init__(self) -> None:
            super().__init__(daemon=True, name="fake-watchdog-observer")

        def stop(self) -> None:  # type: ignore[override]
            stop_called.set()

        def run(self) -> None:
            nonlocal caught
            try:
                state.file_observer = cast(Any, self)
                FileWatcher.stop_file_watching(state)
            except Exception as exc:  # pragma: no cover
                caught = exc
            finally:
                done.set()

    observer = FakeObserver()
    observer.start()

    assert done.wait(timeout=2.0)
    assert stop_called.is_set()
    assert caught is None
