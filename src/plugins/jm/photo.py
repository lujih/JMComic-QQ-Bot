import shutil
import tempfile
import threading
import asyncio

from jmcomic import Feature, jm_log
from jmcomic.jm_exception import MissingAlbumPhotoException, RequestRetryAllFailException

from jm_option import get_option as _get_option
from plugins.jm.cmd import jm_cmd
from plugins.jm.common import (
    _cleanup_stale_dirs,
    run_sync,
    _semaphore,
    _is_cache_valid,
    _make_out_path,
    _get_dl_tmp,
    _clear_cooldown,
    _try_lock_album_by_aid,
    _unlock_album_by_aid,
    _TMP_DIR,
)
from plugins.jm.progress import ProgressJmDownloader
from plugins.jm.upload import _upload_and_cleanup


async def _download_photo(bot, event, photo_id: str, cooldown_key: str):
    if not _try_lock_album_by_aid(photo_id):
        jm_log('jm.photo', f'忽略重复请求 p{photo_id}')
        return
    try:
        await _download_photo_impl(bot, event, photo_id, cooldown_key)
    finally:
        _unlock_album_by_aid(photo_id)


async def _download_photo_impl(bot, event, photo_id: str, cooldown_key: str):
    await run_sync(_cleanup_stale_dirs)
    pdf_path = _make_out_path(photo_id, 'pdf')

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    try:
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            photo = await asyncio.wait_for(cl.get_photo_detail(photo_id), timeout=60)
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 查询超时，请稍后再试")
    except MissingAlbumPhotoException:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 章节不存在，请检查 ID")
    except RequestRetryAllFailException:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 查询失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log('jm.photo.detail', '查询单章详情失败', e)
        await jm_cmd.finish("❌ 查询失败")

    await jm_cmd.send(
        f"📖 {photo.name}\n"
        f"🆔 p{photo.photo_id} | 🖼️ {len(photo)}页"
    )

    extra = Feature.export_pdf(pdf_dir=str(_TMP_DIR), filename_rule='Pid')

    cancel_event = threading.Event()

    def _dl():
        dler = ProgressJmDownloader(option, cancel_event=cancel_event)
        with dler:
            dler.add_features(extra, 'download_photo')
            dler.download_by_photo_detail(photo)
            dler.raise_if_has_exception()

    try:
        async with _semaphore:
            if _is_cache_valid(pdf_path):
                await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)
                return

            pdf_path.unlink(missing_ok=True)

            await run_sync(_dl, timeout=120)
    except asyncio.TimeoutError:
        cancel_event.set()
        await asyncio.sleep(2)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        cancel_event.set()
        jm_log('jm.photo.download', f'下载章节 {photo_id} 失败', e)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 下载失败，请稍后再试")

    if not pdf_path.exists():
        # 清理下载工作目录
        dl_dir = _get_dl_tmp() / photo_id
        if dl_dir.exists():
            shutil.rmtree(dl_dir, ignore_errors=True)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)
