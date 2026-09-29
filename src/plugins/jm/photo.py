from jmcomic import Feature

from plugins.jm.common import (
    _download_entity,
    _TMP_DIR,
)


async def _download_photo(bot, event, photo_id: str, cooldown_key: str):
    # 处理锁由 _download_entity 在拿到 entity 后按「所属专辑 id」获取（见 _try_lock_dl_root），
    # 与 album 路径共用同一把锁——Bd_Aid_Pid 下本章节的图片目录就在专辑根下面。
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
        dl_timeout=120,
        ext='pdf',
        fmt_name='PDF',
        cache_prefix='p',
    )
