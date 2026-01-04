import asyncio
import threading
import time


def test_zai_background_tasks_race():
    """Test potential race condition in ZAI connector _background_tasks pattern"""

    class MockBackend:
        def __init__(self):
            self._background_tasks: set[asyncio.Task[Any]] = set()
            self.task_count = 0

        async def schedule_task(self):
            async def worker():
                await asyncio.sleep(0.1)
                self.task_count += 1

            task = asyncio.create_task(worker())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    backend = MockBackend()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    time.sleep(0.1)

    # Schedule multiple tasks concurrently from different threads
    threads = []

    async def schedule_many():
        tasks = []
        for i in range(10):
            await asyncio.sleep(0.001)
            await backend.schedule_task()
            tasks.append(backend._background_tasks.copy())
        return tasks

    try:
        future = asyncio.run_coroutine_threadsafe(schedule_many(), loop)
        result_sets = future.result(timeout=2)

        time.sleep(0.2)

        print(f"  Tasks scheduled: {len(result_sets[-1])}")
        print(f"  Tasks completed: {backend.task_count}")

        # Check for inconsistency
        max_tasks = max(len(s) for s in result_sets) if result_sets else 0
        if max_tasks > 1:
            print(f"  WARNING: Multiple tasks in set simultaneously: {max_tasks}")

        # All tasks should complete
        if backend.task_count != 10:
            print(
                f"  Race condition detected: expected 10 completed, got {backend.task_count}"
            )
            loop.call_soon_threadsafe(loop.stop)
            return True

        print("  No race detected")
    except Exception as e:
        print(f"  Error: {e}")

    loop.call_soon_threadsafe(loop.stop)
    return False


if __name__ == "__main__":
    detected = False
    for i in range(5):
        print(f"\n--- Run {i+1}/5 ---")
        if test_zai_background_tasks_race():
            detected = True
            break

    if detected:
        print("\nRACE CONDITION CONFIRMED!")
        exit(1)
    else:
        print("\nNo race detected in multiple runs")
        exit(0)
