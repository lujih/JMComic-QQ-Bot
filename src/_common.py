import asyncio
import concurrent.futures
from functools import partial

from jmcomic import jm_log


async def run_sync(func, *args, timeout=180, **kwargs):
    loop = asyncio.get_running_loop()
    fn = partial(func, *args, **kwargs)
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix='run_sync'
    )
    future = loop.run_in_executor(executor, fn)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        name = getattr(func, '__name__', str(func))
        jm_log('run_sync', f'超时: {name}(timeout={timeout}s)')
        raise
    finally:
        executor.shutdown(wait=False)
