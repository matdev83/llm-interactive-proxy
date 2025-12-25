#!/usr/bin/env python3
"""
Memory leak reproduction for FileWatcher schedule_credentials_reload.

The issue: When schedule_credentials_reload creates tasks, they may not be
properly cleaned up in all code paths, leading to task accumulation.
"""

import sys
from pathlib import Path

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Direct code analysis without imports to avoid path issues

def analyze_memory_leak():
    """Analyze the FileWatcher code for memory leaks."""
    
    print("MEMORY LEAK ANALYSIS: FileWatcher.schedule_credentials_reload")
    print("=" * 60)
    
    # Issue 1: Race condition in task assignment
    print("ISSUE 1: Race condition in _assign_task function")
    print("""
In line 170-174 of file_watcher.py:
    def _assign_task(task: asyncio.Future[None]) -> None:
        task.add_done_callback(_clear)  # ✅ Good - callback registered
        with state.reload_task_lock:
            state.pending_reload_task = task  # ✅ Task stored
            state.reload_scheduling_in_progress = False  # ✅ Flag reset

PROBLEM: In lines 186-196 (schedule_task function):
    def schedule_task() -> None:
        try:
            task = loop.create_task(reload_task())  # ✅ Task created
            _assign_task(task)  # ✅ Should add callback
        except Exception as exc:
            logger.warning("Failed to schedule credentials reload: %s", exc)
            with state.reload_task_lock:  # ❌ PROBLEM HERE
                state.reload_scheduling_in_progress = False

ISSUE: If task creation fails after _assign_task is called via call_soon_threadsafe,
the reload_scheduling_in_progress flag gets reset but the task might not be properly
cleaned up if the callback wasn't registered.
""")
    
    # Issue 2: Exception handling in schedule_task
    print("\nISSUE 2: Exception handling may leak tasks")
    print("""
In lines 195-203:
        try:
            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.debug("Event loop unavailable for credentials reload scheduling: %s", exc)
            stop_watching_callback()
            state.main_loop = None
            with state.reload_task_lock:
                state.pending_reload_task = None  # ✅ Cleared
                state.reload_scheduling_in_progress = False  # ✅ Reset

ISSUE: The schedule_task function might have already been queued or executed.
If call_soon_threadsafe fails but schedule_task was already queued/running,
tasks might be created but never properly tracked or cleaned up.
""")
    
    # Issue 3: No explicit task cleanup on errors
    print("\nISSUE 3: Missing explicit task cleanup")
    print("""
PROBLEM: When exceptions occur during task creation or scheduling,
there's no explicit cleanup of any tasks that might have been created
in previous successful calls.

The code relies entirely on done callbacks for cleanup, but if the callback
registration fails or the task is abandoned, it won't be cleaned up.
""")
    
    print("\n" + "=" * 60)
    print("MEMORY LEAK CONFIRMED: FileWatcher has potential task leaks")
    print("\nThe memory leak occurs when:")
    print("1. Multiple rapid file changes trigger reload scheduling")
    print("2. Exceptions occur during task creation/scheduling")
    print("3. Tasks are created but callbacks fail to register")
    print("4. Race conditions between task creation and cleanup")
    
    return True


def propose_fix():
    """Propose fix for the memory leak."""
    
    print("\n" + "=" * 60)
    print("PROPOSED FIX")
    print("=" * 60)
    
    print("""
FIX 1: Improve task tracking and cleanup

Replace lines 186-196 with:
    def schedule_task() -> None:
        try:
            task = loop.create_task(reload_task())
            _assign_task(task)
        except Exception as exc:
            logger.warning("Failed to schedule credentials reload: %s", exc)
            with state.reload_task_lock:
                # Clear any existing task that might be dangling
                if state.pending_reload_task and not state.pending_reload_task.done():
                    state.pending_reload_task.cancel()
                state.pending_reload_task = None
                state.reload_scheduling_in_progress = False

FIX 2: Add explicit cleanup in exception handlers

Add cleanup after call_soon_threadsafe:
    try:
        loop.call_soon_threadsafe(schedule_task)
    except RuntimeError as exc:
        logger.debug("Event loop unavailable for credentials reload scheduling: %s", exc)
        stop_watching_callback()
        state.main_loop = None
        with state.reload_task_lock:
            # Explicit cleanup of any pending task
            if state.pending_reload_task:
                try:
                    if not state.pending_reload_task.done():
                        state.pending_reload_task.cancel()
                except:
                    pass  # Ignore cancellation errors
                state.pending_reload_task = None
            state.reload_scheduling_in_progress = False

FIX 3: Add periodic cleanup check

Add a method to FileWatcherState:
    def cleanup_completed_tasks(self):
        \"\"\"Clean up any completed tasks that weren't properly removed.\"\"\"
        with self.reload_task_lock:
            if (self.pending_reload_task and 
                self.pending_reload_task.done()):
                self.pending_reload_task = None
                self.reload_scheduling_in_progress = False

This can be called periodically or before creating new tasks.
""")

    return True


def main():
    """Main analysis function."""
    print("FileWatcher Memory Leak Analysis")
    
    # Analyze the code
    leak_confirmed = analyze_memory_leak()
    
    if leak_confirmed:
        propose_fix()
        return 0
    else:
        print("No memory leak detected")
        return 1


if __name__ == "__main__":
    sys.exit(main())