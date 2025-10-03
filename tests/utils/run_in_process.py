import asyncio
from collections.abc import Callable, Coroutine
from multiprocessing import Process, Queue
from typing import Any


def _run_in_process(
    target: Callable[..., Coroutine[Any, Any, None]],
    queue: Queue,
    *args: Any,
    **kwargs: Any,
) -> None:
    try:
        result = asyncio.run(target(*args, **kwargs))
        queue.put(result)
    except Exception as e:
        queue.put(e)


async def run_in_process(
    target: Callable[..., Coroutine[Any, Any, None]], *args: Any, **kwargs: Any
) -> None:
    queue: Queue[Any] = Queue()
    process = Process(
        target=_run_in_process, args=(target, queue, *args), kwargs=kwargs
    )
    process.start()
    process.join()
    result = queue.get()
    if isinstance(result, Exception):
        raise result
