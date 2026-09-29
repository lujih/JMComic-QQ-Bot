from jmcomic import JmAsyncDownloader


class ProgressJmDownloader(JmAsyncDownloader):
    """下载器子类化扩展点（当前无额外行为）。

    这里曾经有个 cancel_event，在 before_photo 里检查并给剩余章节置 photo.skip。
    但三处 cancel_event.set() 全部发生在 asyncio.wait_for 抛错之后——那时协程
    已经被取消，before_photo 不会再被调用，属于彻头彻尾的死代码（2026-09-29 移除）。

    若要重新引入「优雅取消」，正确做法是给在下载的章节留一个收尾窗口，例如：
        dl_task = asyncio.ensure_future(_dl())
        await asyncio.wait_for(asyncio.shield(dl_task), dl_timeout)   # 超时后 shield 让它继续跑
        → 捕获 TimeoutError 后 cancel_event.set()，再给 dl_task 一个短的宽限期
        → 宽限期耗尽才 dl_task.cancel()
    而不是像原来那样在 except 分支里直接置位。

    注意基类把 before_photo/after_photo/after_album 派发到解码线程池执行
    （_run_in_decode_pool），这里覆写的钩子必须写成 `async def`。
    """
    pass
