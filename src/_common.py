import asyncio
import concurrent.futures
from functools import partial

from jmcomic import jm_log

_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix='jm_sync'
)


async def run_sync(func, *args, timeout=180, **kwargs):
    loop = asyncio.get_running_loop()
    fn = partial(func, *args, **kwargs)
    future = loop.run_in_executor(_THREAD_POOL, fn)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        name = getattr(func, '__name__', str(func))
        jm_log('run_sync', f'超时: {name}(timeout={timeout}s) — 底层线程继续运行，无法取消')
        raise
