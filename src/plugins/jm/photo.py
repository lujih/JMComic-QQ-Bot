from jmcomic import Feature, jm_log

from plugins.jm.cmd import jm_cmd
from plugins.jm.common import (
    _try_lock_photo_by_pid,
    _unlock_photo_by_pid,
    _clear_cooldown,
    _download_entity,
    _TMP_DIR,
)


async def _download_photo(bot, event, photo_id: str, cooldown_key: str):
    if not _try_lock_photo_by_pid(photo_id):
        _clear_cooldown(cooldown_key)
        jm_log('jm.photo', f'忽略重复请求 p{photo_id}')
        await jm_cmd.finish("⏳ 该章节正在下载中，请稍候再试")
    try:
        extra = Feature.export_pdf(pdf_dir=str(_TMP_DIR), filename_rule='p{Pid}')

        def make_info_msg(photo):
            return (
                f"📖 {photo.name}\n"
                f"🆔 p{photo.photo_id} | 🖼️ {len(photo)}页"
            )

        async def _dl_by_photo(dler, ent):
            await dler.download_by_photo_detail(ent)

        await _download_entity(bot, event, photo_id, cooldown_key,
            log_tag='jm.photo',
            fetch_fn=lambda cl, _id: cl.get_photo_detail(_id),
            make_info_msg=make_info_msg,
            extra=extra,
            download_method_fn=_dl_by_photo,
            dler_tag='download_photo',
            dl_timeout=120,
            ext='pdf',
            fmt_name='PDF',
            cache_prefix='p',
        )
    finally:
        _unlock_photo_by_pid(photo_id)
