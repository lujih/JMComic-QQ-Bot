import shutil
import tempfile
import threading
import asyncio

from jmcomic import JmcomicException

from jm_option import get_option as _get_option
from plugins.jm._cmd import jm_cmd
from plugins.jm.common import (
    _cleanup_stale_dirs,
    _run_sync,
    _semaphore,
    _is_cache_valid,
    _make_out_path,
    _make_progress_cb,
    _clear_cooldown,
    FORMAT_MAP,
    _DEFAULT_FMT,
    _TMP_DIR,
)
from plugins.jm.progress import ProgressJmDownloader
from plugins.jm.upload import _upload_and_cleanup


async def _download_album(bot, event, album_id: str, cooldown_key: str, fmt=_DEFAULT_FMT):
    _cleanup_stale_dirs()
    group_id = event.group_id
    loop = asyncio.get_running_loop()
    feature_cls, ext, fmt_name = FORMAT_MAP[fmt]

    progress = _make_progress_cb(bot, group_id, loop)
    out_path = _make_out_path(album_id, ext)

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    client = option.build_jm_client()
    try:
        album = await _run_sync(client.get_album_detail, album_id)
    except JmcomicException as e:
        await jm_cmd.finish(f"❌ 查询失败: {e}")

    tags_str = f"\n🏷️ {'、'.join(album.tags[:5])}" if album.tags else ""
    await jm_cmd.send(
        f"📖 {album.name}\n"
        f"🆔 JM{album.id} | ✍️ {album.author} | 📄 {len(album)}章 🖼️ {album.page_count}页"
        f"{tags_str}"
    )

    if _is_cache_valid(out_path):
        progress(f"📦 命中缓存，直接发送 {fmt_name}……")
        await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)
        return

    progress(f"⏳ 正在下载并生成 {fmt_name}……")

    out_path.unlink(missing_ok=True)

    extra = feature_cls(**{f'{ext}_dir' if ext != 'png' else 'img_dir': str(_TMP_DIR)}, filename_rule='Aid')

    cancel_event = threading.Event()

    def _dl():
        dler = ProgressJmDownloader(option, progress, fmt_name=fmt_name, cancel_event=cancel_event)
        with dler:
            dler.add_features(extra, 'download_album')
            dler.download_by_album_detail(album)
            dler.raise_if_has_exception()

    async with _semaphore:
        try:
            await _run_sync(_dl, timeout=300)
        except asyncio.TimeoutError:
            cancel_event.set()
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载超时，请稍后再试")
        except Exception as e:
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not out_path.exists():
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish(f"❌ {fmt_name} 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)
