import re
import time
import shutil
import tempfile
import asyncio
import threading
from collections import OrderedDict
from pathlib import Path

from jmcomic import Feature, jm_log
from _common import run_sync

COOLDOWN_SECONDS = 15

FORMAT_MAP = {
    'pdf':     (Feature.export_pdf,     'pdf', 'PDF'),
    'zip':     (Feature.export_zip,     'zip', 'ZIP'),
    'longimg': (Feature.export_long_img, 'png', '长图'),
}

_DEFAULT_FMT = 'pdf'
_last_use: OrderedDict[str, float] = OrderedDict()
_cooldown_lock = threading.Lock()
_MAX_COOLDOWN_ENTRIES = 10000

_semaphore = asyncio.Semaphore(3)
_processing_albums: set[str] = set()
_processing_lock = threading.Lock()

_TMP_DIR = Path(tempfile.gettempdir()) / "jm"
_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _get_dl_tmp() -> Path:
    try:
        from jm_option import get_option
        opt = get_option()
        return Path(opt.dir_rule.base_dir)
    except Exception:
        return Path(tempfile.gettempdir()) / "jm_dl"


def _cleanup_stale_dirs():
    now = time.time()
    for d in [_get_dl_tmp(), _TMP_DIR]:
        if not d.exists():
            continue
        try:
            for entry in d.iterdir():
                if not entry.is_dir():
                    continue
                if now - entry.stat().st_mtime > 1800:
                    shutil.rmtree(entry, ignore_errors=True)
        except OSError as e:
            jm_log('jm.common.cleanup', '清理过期目录失败', e)


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
    try:
        return path.exists() and time.time() - path.stat().st_mtime < max_age
    except OSError:
        return False


def _make_out_path(id_str: str, ext: str) -> Path:
    return _TMP_DIR / f"{id_str}.{ext}"


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


def _try_lock_album(key: str) -> bool:
    with _processing_lock:
        if key in _processing_albums:
            return False
        _processing_albums.add(key)
        return True


def _delayed_unlock(key: str):
    with _processing_lock:
        _processing_albums.discard(key)


def _unlock_album(key: str):
    threading.Timer(COOLDOWN_SECONDS, _delayed_unlock, args=(key,)).start()
