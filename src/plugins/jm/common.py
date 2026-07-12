import re
import time
import shutil
import tempfile
import asyncio
import threading
from collections import OrderedDict
from pathlib import Path

from jmcomic import Feature, jm_log
from jmcomic.jm_exception import MissingAlbumPhotoException, RequestRetryAllFailException
from _common import run_sync
from plugins.jm.cmd import jm_cmd
from plugins.jm.progress import ProgressJmDownloader

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
_STALE_AGE = 1800
_MAX_CACHE_ENTRIES = 50
_SEEN_TTL = 120
_MAX_SEEN_IDS = 1000

_semaphore = asyncio.Semaphore(2)
_processing_albums: set[str] = set()
_processing_lock = threading.Lock()

_seen_message_ids: dict[int, float] = {}
_LOCK_SEEN_IDS = threading.Lock()

_TMP_DIR = Path(tempfile.gettempdir()) / "jm"
_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _get_dl_tmp() -> Path:
    try:
        from jm_option import get_option
        opt = get_option()
        return Path(opt.dir_rule.base_dir)
    except Exception as e:
        jm_log('jm.common', '配置加载失败，回退临时目录', e)
        return Path(tempfile.gettempdir()) / "jm_dl"


def _cleanup_stale_dirs() -> int:
    now = time.time()
    total = 0
    for d in [_get_dl_tmp(), _TMP_DIR]:
        if not d.exists():
            continue
        try:
            # 按时间清理：删除超过 _STALE_AGE 的目录和文件
            for entry in d.iterdir():
                if now - entry.stat().st_mtime > _STALE_AGE:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
                    total += 1

            # 按数量清理：超过 _MAX_CACHE_ENTRIES 时删除最旧的（目录 + 文件）
            entries = sorted(
                d.iterdir(),
                key=lambda e: e.stat().st_mtime,
            )
            while len(entries) > _MAX_CACHE_ENTRIES:
                e = entries[0]
                if e.is_dir():
                    shutil.rmtree(e, ignore_errors=True)
                else:
                    e.unlink(missing_ok=True)
                total += 1
                entries = entries[1:]
        except OSError as e:
            jm_log('jm.common.cleanup', '清理失败', e)

    return total


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


def _is_cache_valid(path: Path, max_age=_STALE_AGE):
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


def _is_dup_message(message_id: int) -> bool:
    now = time.time()
    with _LOCK_SEEN_IDS:
        if message_id in _seen_message_ids:
            return True
        _seen_message_ids[message_id] = now
        if len(_seen_message_ids) > _MAX_SEEN_IDS:
            stale = [k for k, v in _seen_message_ids.items() if now - v > _SEEN_TTL]
            for k in stale:
                del _seen_message_ids[k]
        return False


def _try_lock_album_by_aid(aid: str) -> bool:
    with _processing_lock:
        if aid in _processing_albums:
            return False
        _processing_albums.add(aid)
        return True


def _try_lock_photo_by_pid(pid: str) -> bool:
    key = f'p:{pid}'
    with _processing_lock:
        if key in _processing_albums:
            return False
        _processing_albums.add(key)
        return True


def _unlock_photo_by_pid(pid: str):
    with _processing_lock:
        _processing_albums.discard(f'p:{pid}')


def _unlock_album_by_aid(aid: str):
    with _processing_lock:
        _processing_albums.discard(aid)


async def _download_entity(
    bot, event,
    entity_id: str,
    cooldown_key: str,
    *,
    log_tag: str,
    fetch_fn,
    make_info_msg,
    extra,
    download_method_fn,
    dler_tag: str,
    dl_timeout: int,
    ext: str,
    fmt_name: str,
):
    out_path = _make_out_path(entity_id, ext)

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    try:
        from jm_option import get_option as _get_option
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            entity = await asyncio.wait_for(fetch_fn(cl, entity_id), timeout=60)
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', f'查询详情超时: {entity_id}')
        await jm_cmd.finish("❌ 查询超时，请稍后再试")
    except MissingAlbumPhotoException:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', f'实体不存在: {entity_id}')
        await jm_cmd.finish("❌ 实体不存在，请检查 ID")
    except RequestRetryAllFailException:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', f'查询详情失败: API 不可达 ({entity_id})')
        await jm_cmd.finish("❌ 查询失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', '查询详情失败', e)
        await jm_cmd.finish("❌ 查询失败")

    await jm_cmd.send(make_info_msg(entity))

    cancel_event = threading.Event()

    def _dl():
        if cancel_event.is_set():
            return
        dler = ProgressJmDownloader(option, cancel_event=cancel_event)
        with dler:
            dler.add_features(extra, dler_tag)
            download_method_fn(dler, entity)
            dler.raise_if_has_exception()

    if _is_cache_valid(out_path):
        from plugins.jm.upload import _upload_and_cleanup
        await _upload_and_cleanup(bot, event, out_path, entity_id, cooldown_key, ext, fmt_name)
        return

    try:
        async with _semaphore:
            out_path.unlink(missing_ok=True)
            await run_sync(_dl, timeout=dl_timeout)
    except asyncio.TimeoutError:
        cancel_event.set()
        jm_log(f'{log_tag}.download', f'下载超时 ({entity_id})')
        await asyncio.sleep(2)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        cancel_event.set()
        jm_log(f'{log_tag}.download', f'下载 {entity_id} 失败', e)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 下载失败，请稍后再试")

    if not out_path.exists():
        dl_dir = _get_dl_tmp() / entity_id
        if dl_dir.exists():
            shutil.rmtree(dl_dir, ignore_errors=True)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish(f"❌ {fmt_name} 生成失败，文件未找到")

    from plugins.jm.upload import _upload_and_cleanup
    await _upload_and_cleanup(bot, event, out_path, entity_id, cooldown_key, ext, fmt_name)
