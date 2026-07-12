from jmcomic import jm_log

from plugins.jm.common import (
    _try_lock_album_by_aid,
    _unlock_album_by_aid,
    _download_entity,
    FORMAT_MAP,
    _DEFAULT_FMT,
    _TMP_DIR,
)


async def _download_album(bot, event, album_id: str, cooldown_key: str, fmt=_DEFAULT_FMT):
    if not _try_lock_album_by_aid(album_id):
        jm_log('jm.album', f'忽略重复请求 album_id={album_id}')
        return
    try:
        feature_cls, ext, fmt_name = FORMAT_MAP[fmt]
        extra = feature_cls(
            **{f'{ext}_dir' if ext != 'png' else 'img_dir': str(_TMP_DIR)},
            filename_rule='Aid'
        )

        def make_info_msg(album):
            tags_str = f"\n🏷️ {'、'.join(album.tags[:5])}" if album.tags else ""
            return (
                f"📖 {album.name}\n"
                f"🆔 JM{album.id} | ✍️ {album.author} | 📄 {len(album)}章 🖼️ {album.page_count or '?'}页"
                f"{tags_str}"
            )

        await _download_entity(bot, event, album_id, cooldown_key,
            log_tag='jm.album',
            fetch_fn=lambda cl, _id: cl.get_album_detail(_id),
            make_info_msg=make_info_msg,
            extra=extra,
            download_method_fn=lambda dler, ent: dler.download_by_album_detail(ent),
            dler_tag='download_album',
            dl_timeout=300,
            ext=ext,
            fmt_name=fmt_name,
        )
    finally:
        _unlock_album_by_aid(album_id)
