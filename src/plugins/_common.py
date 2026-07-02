import asyncio


async def run_sync(func, *args, timeout=180, **kwargs):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=timeout,
    )
