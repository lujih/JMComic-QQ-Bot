import asyncio
import concurrent.futures
from functools import partial

from jmcomic import jm_log

# 模块级共享线程池：原实现每次调用都 new 一个 ThreadPoolExecutor(max_workers=1)，
# 高频调用（如 /mv 每条磁力链都要过一次 Scrapling 同步搜索）会反复创建/销毁线程，
# 既慢又白白堆积线程对象。这里一次性建池复用，线程数给到 8 覆盖并发搜索。
# 进程退出时 Python 会回收该池，无需显式关闭。
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix='run_sync',
)


async def run_sync(func, *args, timeout=180, **kwargs):
    loop = asyncio.get_running_loop()
    fn = partial(func, *args, **kwargs)
    future = loop.run_in_executor(_EXECUTOR, fn)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        name = getattr(func, '__name__', str(func))
        jm_log('run_sync', f'超时: {name}(timeout={timeout}s)')
        raise
