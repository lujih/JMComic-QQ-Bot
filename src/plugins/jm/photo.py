import shutil
import tempfile
import threading
import asyncio

from jmcomic import Feature, jm_log

from jm_option import get_option as _get_option
from plugins.jm.cmd import jm_cmd
from plugins.jm.common import (
    _cleanup_stale_dirs,
    _run_sync,
    _semaphore,
    _is_cache_valid,
    _make_out_path,
    _clear_cooldown,
    _TMP_DIR,
)
from plugins.jm.progress import ProgressJmDownloader
from plugins.jm.upload import _upload_and_cleanup


async def _download_photo(bot, event, photo_id: str, cooldown_key: str):
    _cleanup_stale_dirs()
    pdf_path = _make_out_path(photo_id, 'pdf')

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    client = option.build_jm_client()
    try:
        photo = await _run_sync(client.get_photo_detail, photo_id)
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log('photo.detail', f'查询单章详情失败: {e}')
        await jm_cmd.finish("❌ 查询失败")

    await jm_cmd.send(
        f"📖 {photo.name}\n"
        f"🆔 p{photo.photo_id} | 🖼️ {len(photo)}页"
    )

    if _is_cache_valid(pdf_path):
        await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)
        return

    pdf_path.unlink(missing_ok=True)

    extra = Feature.export_pdf(pdf_dir=str(_TMP_DIR), filename_rule='Pid')

    cancel_event = threading.Event()

    def _dl():
        dler = ProgressJmDownloader(option, cancel_event=cancel_event)
        with dler:
            dler.add_features(extra, 'download_photo')
            dler.download_by_photo_detail(photo)
            dler.raise_if_has_exception()

    async with _semaphore:
        try:
            await _run_sync(_dl, timeout=120)
        except asyncio.TimeoutError:
            cancel_event.set()
            await asyncio.sleep(3)
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载超时，请稍后再试")
        except Exception:
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载失败，请稍后再试")

    if not pdf_path.exists():
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)
