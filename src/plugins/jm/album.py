import shutil
import tempfile
import threading
import asyncio

from jmcomic import jm_log
from jmcomic.jm_exception import MissingAlbumPhotoException, RequestRetryAllFailException

from jm_option import get_option as _get_option
from plugins.jm.cmd import jm_cmd
from plugins.jm.common import (
    _cleanup_stale_dirs,
    run_sync,
    _semaphore,
    _is_cache_valid,
    _make_out_path,
    _clear_cooldown,
    FORMAT_MAP,
    _DEFAULT_FMT,
    _TMP_DIR,
)
from plugins.jm.progress import ProgressJmDownloader
from plugins.jm.upload import _upload_and_cleanup


async def _download_album(bot, event, album_id: str, cooldown_key: str, fmt=_DEFAULT_FMT):
    _cleanup_stale_dirs()
    feature_cls, ext, fmt_name = FORMAT_MAP[fmt]

    out_path = _make_out_path(album_id, ext)

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    try:
        async with option.new_jm_async_client() as cl:
            album = await asyncio.wait_for(cl.get_album_detail(album_id), timeout=60)
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 查询超时，请稍后再试")
    except MissingAlbumPhotoException:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 本子不存在，请检查 ID")
    except RequestRetryAllFailException:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 查询失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log('album.detail', f'查询本子详情失败: {e}')
        await jm_cmd.finish("❌ 查询失败")

    tags_str = f"\n🏷️ {'、'.join(album.tags[:5])}" if album.tags else ""
    await jm_cmd.send(
        f"📖 {album.name}\n"
        f"🆔 JM{album.id} | ✍️ {album.author} | 📄 {len(album)}章 🖼️ {album.page_count or '?'}页"
        f"{tags_str}"
    )

    if _is_cache_valid(out_path):
        await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)
        return

    out_path.unlink(missing_ok=True)

    kw = {f'{ext}_dir' if ext != 'png' else 'img_dir': str(_TMP_DIR)}
    extra = feature_cls(**kw, filename_rule='Aid')

    cancel_event = threading.Event()

    def _dl():
        dler = ProgressJmDownloader(option, cancel_event=cancel_event)
        with dler:
            dler.add_features(extra, 'download_album')
            dler.download_by_album_detail(album)
            dler.raise_if_has_exception()

    async with _semaphore:
        try:
            await run_sync(_dl, timeout=300)
        except asyncio.TimeoutError:
            cancel_event.set()
            await asyncio.sleep(3)
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载超时，请稍后再试")
        except Exception:
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载失败，请稍后再试")

    if not out_path.exists():
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish(f"❌ {fmt_name} 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)
