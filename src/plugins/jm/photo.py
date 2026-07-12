from jmcomic import Feature, jm_log

from plugins.jm.common import (
    _try_lock_photo_by_pid,
    _unlock_photo_by_pid,
    _download_entity,
    _TMP_DIR,
)


async def _download_photo(bot, event, photo_id: str, cooldown_key: str):
    if not _try_lock_photo_by_pid(photo_id):
        jm_log('jm.photo', f'忽略重复请求 p{photo_id}')
        return
    try:
        extra = Feature.export_pdf(pdf_dir=str(_TMP_DIR), filename_rule='Pid')

        def make_info_msg(photo):
            return (
                f"📖 {photo.name}\n"
                f"🆔 p{photo.photo_id} | 🖼️ {len(photo)}页"
            )

        await _download_entity(bot, event, photo_id, cooldown_key,
            log_tag='jm.photo',
            fetch_fn=lambda cl, _id: cl.get_photo_detail(_id),
            make_info_msg=make_info_msg,
            extra=extra,
            download_method_fn=lambda dler, ent: dler.download_by_photo_detail(ent),
            dler_tag='download_photo',
            dl_timeout=120,
            ext='pdf',
            fmt_name='PDF',
        )
    finally:
        _unlock_photo_by_pid(photo_id)
