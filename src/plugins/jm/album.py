from plugins.jm.common import (
    _download_entity,
    FORMAT_MAP,
    _DEFAULT_FMT,
    _TMP_DIR,
)


async def _download_album(bot, event, album_id: str, cooldown_key: str, fmt=_DEFAULT_FMT):
    # 处理锁由 _download_entity 在拿到 entity 后按「所属专辑 id」获取（见 _try_lock_dl_root），
    # 与 photo 路径共用同一把锁——Bd_Aid_Pid 下两条路径写同一棵目录树。
    feature_cls, ext, fmt_name = FORMAT_MAP[fmt]
    extra = feature_cls(
        **{f'{ext}_dir' if ext != 'png' else 'img_dir': str(_TMP_DIR)},
        filename_rule='a{Aid}'
    )
    if fmt == 'zip':
        # 先压缩源图再打包（FeatureChain 按序执行，压缩 Feature 须在 export_zip 之前）
        from plugins.jm.compress import CompressZipFeature
        extra = CompressZipFeature() + extra

    def make_info_msg(album):
        tags_str = f"\n🏷️ {'、'.join(album.tags[:5])}" if album.tags else ""
        return (
            f"📖 {album.name}\n"
            f"🆔 JM{album.id} | ✍️ {album.author} | 📄 {len(album)}章 🖼️ {album.page_count or '?'}页"
            f"{tags_str}"
        )

    async def _dl_by_album(dler, ent):
        await dler.download_by_album_detail(ent)

    await _download_entity(bot, event, album_id, cooldown_key,
        log_tag='jm.album',
        fetch_fn=lambda cl, _id: cl.get_album_detail(_id),
        make_info_msg=make_info_msg,
        extra=extra,
        download_method_fn=_dl_by_album,
        dl_timeout=300,
        ext=ext,
        fmt_name=fmt_name,
        cache_prefix='a',
    )
