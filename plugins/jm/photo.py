import shutil
import tempfile
import threading
import asyncio

from jmcomic import Feature, JmcomicException

from plugins._option import get_option as _get_option
from plugins.database import use_download_quota
from plugins.jm._cmd import jm_cmd
from plugins.jm.common import (
    _cleanup_stale_dirs,
    _run_sync,
    _semaphore,
    _is_cache_valid,
    _make_out_path,
    _last_use,
    _DL_TMP,
    _TMP_DIR,
)
from plugins.jm.progress import ProgressJmDownloader
from plugins.jm.upload import _upload_and_cleanup


async def _download_photo(bot, event, photo_id: str, cooldown_key: str):
    _cleanup_stale_dirs()
    group_id = event.group_id
    loop = asyncio.get_running_loop()

    def progress(msg: str):
        try:
            asyncio.run_coroutine_threadsafe(
                bot.send_group_msg(group_id=group_id, message=msg),
                loop,
            )
        except Exception:
            pass

    pdf_path = _make_out_path(photo_id, 'pdf')

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    client = option.build_jm_client()
    try:
        photo = await _run_sync(client.get_photo_detail, photo_id)
    except JmcomicException as e:
        await jm_cmd.finish(f"❌ 查询失败: {e}")

    await jm_cmd.send(
        f"📖 {photo.name}\n"
        f"🆔 p{photo.photo_id} | 🖼️ {len(photo)}页"
    )

    if _is_cache_valid(pdf_path):
        progress("📦 命中缓存，直接发送 PDF……")
        await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)
        return

    quota = await _run_sync(use_download_quota, event.user_id, event.group_id)
    if not quota['ok']:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(quota['msg'])
    progress(quota['msg'])

    progress(f"⏳ 正在下载章节并生成 PDF……")

    pdf_path.unlink(missing_ok=True)

    extra = Feature.export_pdf(pdf_dir=str(_TMP_DIR), filename_rule='Pid')

    cancel_event = threading.Event()

    def _dl():
        dler = ProgressJmDownloader(option, progress, cancel_event=cancel_event)
        with dler:
            dler.add_features(extra, 'download_photo')
            dler.download_by_photo_detail(photo)
            dler.raise_if_has_exception()

    try:
        async with _semaphore:
            await _run_sync(_dl, timeout=120)
    except asyncio.TimeoutError:
        cancel_event.set()
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not pdf_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)
