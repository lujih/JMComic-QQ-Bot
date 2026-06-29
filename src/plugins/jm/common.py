import re
import time
import shutil
import tempfile
import asyncio
import threading
from collections import OrderedDict
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot

from jmcomic import Feature, jm_log

COOLDOWN_SECONDS = 60

FORMAT_MAP = {
    'pdf':     (Feature.export_pdf,     'pdf', 'PDF'),
    'zip':     (Feature.export_zip,     'zip', 'ZIP'),
    'longimg': (Feature.export_long_img, 'png', '长图'),
}

_DEFAULT_FMT = 'pdf'
_last_use: OrderedDict[str, float] = OrderedDict()
_cooldown_lock = threading.Lock()
_MAX_COOLDOWN_ENTRIES = 10000

_semaphore = asyncio.Semaphore(1)
_TMP_DIR = Path(tempfile.gettempdir()) / "jm"
_DL_TMP = Path(tempfile.gettempdir()) / "jm_dl"
_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_stale_dirs():
    dl = _DL_TMP
    if not dl.exists():
        return
    now = time.time()
    for d in dl.iterdir():
        if not d.is_dir():
            continue
        try:
            if now - d.stat().st_mtime > 1800:
                shutil.rmtree(d, ignore_errors=True)
        except OSError as e:
            jm_log('common.cleanup', f'清理过期目录失败: {e}')


async def _run_sync(func, *args, timeout=180):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args)),
        timeout=timeout,
    )


# Public alias for cross-module use
run_sync = _run_sync


def _parse_format_flags(text: str):
    fmt = _DEFAULT_FMT
    flags = re.findall(r'--(zip|longimg)\b', text)
    unique = set(flags)
    if len(unique) >= 2:
        raise ValueError("不能同时使用 --zip 和 --longimg")
    if len(flags) > len(unique):
        raise ValueError(f"重复使用了 --{flags[0]}，请只指定一次")
    if unique:
        fmt = list(unique)[0]
        text = re.sub(r'--(zip|longimg)\b', '', text).strip()
    return text, fmt


def _is_cache_valid(path: Path, max_age=1800):
    return path.exists() and time.time() - path.stat().st_mtime < max_age


def _make_out_path(id_str: str, ext: str) -> Path:
    return _TMP_DIR / f"{id_str}.{ext}"


def _make_progress_cb(bot: Bot, group_id: int, loop: asyncio.AbstractEventLoop):
    def progress(msg: str):
        try:
            asyncio.run_coroutine_threadsafe(
                bot.send_group_msg(group_id=group_id, message=msg),
                loop,
            )
        except Exception as e:
            jm_log('jm.progress', f'发送进度消息失败: {e}')
    return progress


HELP_TEXT = (
    "📖 JMComic QQ Bot 命令列表\n\n"
    "/jm <本子ID>            下载本子（默认 PDF）\n"
    "/jm <本子ID> --zip      下载并打包为 ZIP\n"
    "/jm <本子ID> --longimg  下载并拼接为长图\n"
    "/jm p<章节ID>           下载单个章节\n"
    "/jm rank [周/月/日]     查看排行榜（默认周榜）\n"
    "/jm random             随机推荐一本\n"
    "/jm help               显示本帮助\n"
    "/jmv <ID>               查看本子详情\n"
    "/jms <关键词>           搜索本子\n"
    "/mv <番号>              搜索番号并返回磁力链接\n"
    "每日早 9:00             自动推送随机推荐到群"
)


def _check_cooldown(key: str) -> int:
    now = time.time()
    with _cooldown_lock:
        while len(_last_use) > _MAX_COOLDOWN_ENTRIES:
            _last_use.popitem(last=False)

        last = _last_use.get(key, 0)
        remaining = COOLDOWN_SECONDS - (now - last)
        if remaining > 0:
            return int(remaining)

        _last_use[key] = now
        _last_use.move_to_end(key)
        return 0


def _clear_cooldown(key: str):
    with _cooldown_lock:
        _last_use.pop(key, None)
