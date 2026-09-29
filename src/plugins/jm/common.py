import re
import time
import shutil
import tempfile
import asyncio
import threading
from collections import OrderedDict
from pathlib import Path

from jmcomic import Feature, jm_log, jm_task_context
from jmcomic.jm_exception import MissingAlbumPhotoException, PartialDownloadFailedException, RequestRetryAllFailException
from plugins.jm.cmd import jm_cmd
from plugins.jm.progress import ProgressJmDownloader

COOLDOWN_SECONDS = 15

FORMAT_MAP = {
    'pdf':     (Feature.export_pdf,     'pdf', 'PDF'),
    'zip':     (Feature.export_zip,     'zip', 'ZIP'),
    'longimg': (Feature.export_long_img, 'png', '长图'),
}

_DEFAULT_FMT = 'pdf'
_last_use: OrderedDict[str, float] = OrderedDict()
_cooldown_lock = threading.Lock()
_MAX_COOLDOWN_ENTRIES = 10000
_STALE_AGE = 1800
_MAX_CACHE_ENTRIES = 50
_SEEN_TTL = 600
_MAX_SEEN_IDS = 1000

_semaphore = asyncio.Semaphore(2)
_processing_albums: set[str] = set()
_processing_lock = threading.Lock()

_seen_message_ids: dict[int, float] = {}
_LOCK_SEEN_IDS = threading.Lock()
_last_seen_cleanup = 0.0

_TMP_DIR = Path(tempfile.gettempdir()) / "jm"
_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _get_dl_tmp() -> Path:
    try:
        from jm_option import get_option
        opt = get_option()
        return Path(opt.dir_rule.base_dir)
    except Exception as e:
        jm_log('jm.common', '配置加载失败，回退临时目录', e)
        return Path(tempfile.gettempdir()) / "jm_dl"


def _cleanup_stale_dirs() -> int:
    now = time.time()
    total = 0
    # 封面临时文件位于 tempfile 根目录（/tmp/jm_cover_*、/tmp/jm_mv_cover_*），不在常规缓存目录内
    tmp_root = Path(tempfile.gettempdir())
    try:
        for entry in tmp_root.iterdir():
            if not entry.is_file():
                continue
            if entry.name.startswith('jm_cover_') or entry.name.startswith('jm_mv_cover_'):
                if now - entry.stat().st_mtime > _STALE_AGE:
                    entry.unlink(missing_ok=True)
                    total += 1
    except OSError:
        pass

    for d in [_get_dl_tmp(), _TMP_DIR]:
        if not d.exists():
            continue
        try:
            # 按时间清理：删除超过 _STALE_AGE 的目录和文件
            for entry in d.iterdir():
                if now - entry.stat().st_mtime > _STALE_AGE:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
                    total += 1

            # 按数量清理：超过 _MAX_CACHE_ENTRIES 时删除最旧的（目录 + 文件）
            entries = sorted(
                d.iterdir(),
                key=lambda e: e.stat().st_mtime,
            )
            while len(entries) > _MAX_CACHE_ENTRIES:
                e = entries[0]
                if e.is_dir():
                    shutil.rmtree(e, ignore_errors=True)
                else:
                    e.unlink(missing_ok=True)
                total += 1
                entries = entries[1:]
        except OSError as e:
            jm_log('jm.common.cleanup', '清理失败', e)

    return total


def _parse_format_flags(text: str):
    fmt = _DEFAULT_FMT
    flags = re.findall(r'--(zip|longimg)\b', text)
    unique = set(flags)
    if len(unique) >= 2:
        raise ValueError("不能同时使用 --zip 和 --longimg")
    if len(flags) > len(unique):
        raise ValueError(f"重复使用了 --{flags[0]}，请只指定一次")
    if unique:
        fmt = list(unique)[0]
        text = re.sub(r'--(zip|longimg)\b', '', text).strip()
    return text, fmt


def _is_cache_valid(path: Path, max_age=_STALE_AGE):
    try:
        st = path.stat()
        return st.st_size > 0 and time.time() - st.st_mtime < max_age
    except OSError:
        return False


def _make_out_path(id_str: str, ext: str) -> Path:
    # id_str 由调用方带命名空间前缀（album: a{id}，photo: p{id}），避免数字碰撞互串
    return _TMP_DIR / f"{id_str}.{ext}"


HELP_TEXT = (
    "📖 JMComic QQ Bot 命令列表\n\n"
    "/jm <本子ID>            下载本子（默认 PDF）\n"
    "/jm <本子ID> --zip      下载并打包为 ZIP\n"
    "/jm <本子ID> --longimg  下载并拼接为长图\n"
    "/jm p<章节ID>           下载单个章节\n"
    "/jm rank [周/月/日]     查看排行榜（默认周榜）\n"
    "/jm random             随机推荐一本\n"
    "/jm help               显示本帮助\n"
    "/jmv <ID>               查看本子详情\n"
    "/jms <关键词>           搜索本子\n"
    "/jmc <ID> [页码]        查看本子评论\n"
    "/mv <番号>              搜索番号并返回磁力链接\n"
    "/ss 图/回复图/裸发      以图搜源（裸发自动用本群最近一张图）\n"
    "每日早 9:00             自动推送随机推荐到群"
)


def _check_cooldown(key: str) -> int:
    now = time.time()
    with _cooldown_lock:
        while len(_last_use) > _MAX_COOLDOWN_ENTRIES:
            _last_use.popitem(last=False)

        last = _last_use.get(key, 0)
        remaining = COOLDOWN_SECONDS - (now - last)
        if remaining > 0:
            return int(remaining)

        _last_use[key] = now
        _last_use.move_to_end(key)
        return 0


def _clear_cooldown(key: str):
    with _cooldown_lock:
        _last_use.pop(key, None)


def _is_dup_message(message_id: int) -> bool:
    global _last_seen_cleanup
    now = time.time()
    with _LOCK_SEEN_IDS:
        if message_id in _seen_message_ids:
            return True
        _seen_message_ids[message_id] = now
        if len(_seen_message_ids) > _MAX_SEEN_IDS or now - _last_seen_cleanup > _SEEN_TTL:
            stale = [k for k, v in _seen_message_ids.items() if now - v > _SEEN_TTL]
            for k in stale:
                del _seen_message_ids[k]
            _last_seen_cleanup = now
        return False


def _try_lock_dl_root(album_id: str) -> bool:
    """以「所属专辑 id」为键互斥。

    锁的是 album 整个下载目录树，而不是本次请求的 entity_id。dir_rule=Bd_Aid_Pid 时，
    album 下载的根是 {base}/{album_id}，photo 下载的 {base}/{album_id}/{photo_id}
    就长在这个根下面——两者物理重叠。按 entity_id 分锁会让两条路径互不排斥，
    于是在下载前的 rmtree 里删掉对方正在写的图片目录；最坏情况是磁盘删除发生在
    after_image 记账之后，PDF 静默缺图却仍被当作完整产物上传。
    """
    with _processing_lock:
        if album_id in _processing_albums:
            return False
        _processing_albums.add(album_id)
        return True


def _unlock_dl_root(album_id: str):
    with _processing_lock:
        _processing_albums.discard(album_id)


async def _download_entity(
    bot, event,
    entity_id: str,
    cooldown_key: str,
    *,
    log_tag: str,
    fetch_fn,
    make_info_msg,
    extra,
    download_method_fn,
    dl_timeout: int,
    ext: str,
    fmt_name: str,
    cache_prefix: str,
):
    out_path = _make_out_path(f"{cache_prefix}{entity_id}", ext)

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    try:
        from jm_option import get_option as _get_option
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            entity = await asyncio.wait_for(fetch_fn(cl, entity_id), timeout=60)
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', f'查询详情超时: {entity_id}')
        await jm_cmd.finish("❌ 查询超时，请稍后再试")
    except MissingAlbumPhotoException:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', f'实体不存在: {entity_id}')
        await jm_cmd.finish("❌ 实体不存在，请检查 ID")
    except RequestRetryAllFailException as e:
        _clear_cooldown(cooldown_key)
        # 传 e：jmcomic ≥2.7.5 的 __str__ 会带上各域名/各次重试的原始异常，
        # 是排查「API 不可达」到底是 DNS、超时还是被风控的唯一线索，不传就白升级了
        jm_log(f'{log_tag}.detail', f'查询详情失败: API 不可达 ({entity_id})', e)
        await jm_cmd.finish("❌ 查询失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.detail', '查询详情失败', e)
        await jm_cmd.finish("❌ 查询失败")

    await jm_cmd.send(make_info_msg(entity))

    if _is_cache_valid(out_path):
        from plugins.jm.upload import _upload_and_cleanup
        await _upload_and_cleanup(bot, event, out_path, entity_id, cooldown_key, ext, fmt_name, dl_dir=None)
        return

    # 处理锁：键是「所属专辑 id」而不是本次请求的 entity_id。
    # option.yml 的 dir_rule 是 Bd_Aid_Pid，album 下载写在 {base}/{album_id}，
    # photo 下载写在 {base}/{album_id}/{photo_id}——photo 的图片目录就在 album 的根下面。
    # 若按 entity_id 分锁（album 用裸 id、photo 用 p:{id}），两条路径互不排斥，
    # 会在下载前的 rmtree 里删掉对方正在写的图片目录；最坏情况是磁盘删除发生在
    # after_image 记账之后，PDF 静默缺图却仍被当作完整产物上传。
    # 改用 album_id 后：album 下载、任意章节下载、同本不同章节并发，全部互斥。
    # 单章本子的 photo.album_id == photo_id（is_single_album），与 album 侧天然同键。
    # 缓存命中路径不碰下载目录，无需加锁。
    dl_root = str(entity.album_id)
    if not _try_lock_dl_root(dl_root):
        _clear_cooldown(cooldown_key)
        jm_log(f'{log_tag}.lock', f'忽略重复请求，专辑 {dl_root} 正在下载中')
        await jm_cmd.finish("⏳ 该本子正在下载中，请稍候再试")

    try:
        cancel_event = threading.Event()

        async def _dl():
            if cancel_event.is_set():
                return
            dler = ProgressJmDownloader(option, cancel_event=cancel_event)
            async with dler:
                # jmcomic ≥2.7.4 起，Feature 的执行时机由 TaskContext 的 download_type 决定，
                # add_features 不再接受 feature_from 参数，且必须在 jm_task_context 内调用。
                # begin_manifest/finish_manifest 不可省：导出插件（img2pdf/zip/long_img）会通过
                # downloader.record_export_filepath 把产物登记进清单，缺清单时插件直接抛
                # 「当前实体没有活动的下载清单」——而该异常会被 _invoke_features_for 吞进日志，
                # 表现为「下载成功但 PDF/ZIP 没生成」，是极难排查的静默失败。
                # dtype 必须由 entity.is_album() 推导：写死会让对应 export Feature 的
                # should_invoke 恒为 False，导出静默不发生且不抛任何异常。
                dtype = 'album' if entity.is_album() else 'photo'
                with jm_task_context(download_type=dtype, jm_id=str(entity_id)):
                    dler.begin_manifest(entity)
                    try:
                        dler.add_features(extra)
                        await download_method_fn(dler, entity)
                    finally:
                        dler.finish_manifest(entity)
                dler.raise_if_has_exception()

        # 清理目标：album 删专辑根（内含所有 Pid 子目录），photo 只删自己的 Pid 子目录。
        # 不能统一用 decide_image_save_dir(entity).parent——那正是 album 的根，
        # photo 会把整个专辑根连同其它章节一起删掉。
        if entity.is_album():
            dl_dir = Path(option.dir_rule.decide_album_root_dir(entity))
        else:
            dl_dir = Path(option.decide_image_save_dir(entity))
        try:
            async with _semaphore:
                out_path.unlink(missing_ok=True)
                if dl_dir.exists():
                    shutil.rmtree(dl_dir, ignore_errors=True)
                await asyncio.wait_for(_dl(), timeout=dl_timeout)
        except asyncio.TimeoutError:
            cancel_event.set()
            out_path.unlink(missing_ok=True)
            shutil.rmtree(dl_dir, ignore_errors=True)
            jm_log(f'{log_tag}.download', f'下载超时 ({entity_id})')
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载超时，请稍后再试")
        except PartialDownloadFailedException as e:
            cancel_event.set()
            jm_log(f'{log_tag}.download', f'部分图片下载失败 ({entity_id}): {e}')
            if out_path.exists() and out_path.stat().st_size > 0:
                from plugins.jm.upload import _upload_and_cleanup
                await jm_cmd.send("⚠️ 部分图片下载失败，文件已生成（可能缺图）")
                await _upload_and_cleanup(bot, event, out_path, entity_id, cooldown_key, ext, fmt_name, dl_dir=dl_dir)
                return
            out_path.unlink(missing_ok=True)
            shutil.rmtree(dl_dir, ignore_errors=True)
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载失败（部分图片缺失），请稍后再试")
        except Exception as e:
            cancel_event.set()
            out_path.unlink(missing_ok=True)
            shutil.rmtree(dl_dir, ignore_errors=True)
            jm_log(f'{log_tag}.download', f'下载 {entity_id} 失败', e)
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish("❌ 下载失败，请稍后再试")

        if not out_path.exists():
            if dl_dir.exists():
                shutil.rmtree(dl_dir, ignore_errors=True)
            _clear_cooldown(cooldown_key)
            await jm_cmd.finish(f"❌ {fmt_name} 生成失败，文件未找到")

        from plugins.jm.upload import _upload_and_cleanup
        await _upload_and_cleanup(bot, event, out_path, entity_id, cooldown_key, ext, fmt_name, dl_dir=dl_dir)
    finally:
        _unlock_dl_root(dl_root)
