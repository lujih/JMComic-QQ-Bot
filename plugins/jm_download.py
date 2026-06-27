import re
import time
import random
import asyncio
import threading
import shutil
import tempfile
from collections import OrderedDict
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import is_type

import httpx

from jmcomic import Feature, JmDownloader, JmcomicException
from plugins._option import get_option as _get_option
from plugins.database import use_download_quota

__plugin_name__ = "jm_download"
__plugin_usage__ = (
    "/jm <ID> — 下载本子\n"
    "/jm p<ID> — 下载单章\n"
    "/jm rank [周/月/日] — 排行榜\n"
    "/jm random — 随机一本\n"
    "/jm help — 查看全部命令"
)

COOLDOWN_SECONDS = 60

FORMAT_MAP = {
    'pdf':     (Feature.export_pdf,     'pdf', 'PDF'),
    'zip':     (Feature.export_zip,     'zip', 'ZIP'),
    'longimg': (Feature.export_long_img, 'png', '长图'),
}

_DEFAULT_FMT = 'pdf'
_last_use: OrderedDict[str, float] = OrderedDict()
_MAX_COOLDOWN_ENTRIES = 10000
_cancel_event = threading.Event()

_semaphore = asyncio.Semaphore(1)
_TMP_DIR = Path(tempfile.gettempdir()) / "jm"
_DL_TMP = Path(tempfile.gettempdir()) / "jm_dl"


def _cleanup_stale_dirs():
    dl = _DL_TMP
    if not dl.exists():
        return
    now = time.time()
    for d in dl.iterdir():
        if not d.is_dir():
            continue
        try:
            if now - d.stat().st_mtime > 1800:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


async def _run_sync(func, *args, timeout=180):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args)),
        timeout=timeout,
    )


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


def _is_cache_valid(path: Path, max_age=1800):
    return path.exists() and time.time() - path.stat().st_mtime < max_age


def _make_out_path(id_str: str, ext: str) -> Path:
    return _TMP_DIR / f"{id_str}.{ext}"


def _check_cooldown(key: str) -> int:
    now = time.time()
    # 惰性清理：限制字典大小
    while len(_last_use) > _MAX_COOLDOWN_ENTRIES:
        _last_use.popitem(last=False)

    last = _last_use.get(key, 0)
    remaining = COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        return int(remaining)

    _last_use[key] = now
    _last_use.move_to_end(key)
    return 0


HELP_TEXT = (
    "📖 JMComic QQ Bot 命令列表\n\n"
    "/jm <本子ID>            下载本子（默认 PDF）\n"
    "/jm <本子ID> --zip      下载并打包为 ZIP\n"
    "/jm <本子ID> --longimg  下载并拼接为长图\n"
    "/jm p<章节ID>           下载单个章节\n"
    "/jm rank [周/月/日]     查看排行榜（默认周榜）\n"
    "/jm random             随机推荐一本\n"
    "/jm help               显示本帮助\n"
    "/sign                  每日签到获取积分（5~99 随机）\n\n"
    "/jmv <ID>               查看本子详情\n"
    "/jms <关键词>           搜索本子\n"
    "每日早 9:00             自动推送随机推荐到群"
)

class ProgressJmDownloader(JmDownloader):
    def __init__(self, option, progress_cb, fmt_name='PDF'):
        super().__init__(option)
        self._cb = progress_cb
        self._fmt_name = fmt_name

    def after_album(self, album):
        if _cancel_event.is_set():
            return
        self._cb(f"📄 正在生成 {self._fmt_name}……")
        super().after_album(album)


jm_cmd = on_command("jm", priority=10, rule=is_type(GroupMessageEvent))


@jm_cmd.handle()
async def handle_jm(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()

    # strip format flags first, so routing doesn't break (e.g. "random --zip")
    try:
        text, fmt = _parse_format_flags(text)
    except ValueError as e:
        await jm_cmd.finish(f"❌ {e}")

    # help
    if text == "help":
        await jm_cmd.finish(HELP_TEXT)

    # rank
    match = re.match(r'^rank\s*(\S*)$', text)
    if match:
        period = match.group(1).strip()
        await _handle_rank(bot, event, period)
        return

    # random
    if text == "random":
        await _handle_random(bot, event)
        return

    # 检查 /jm 123456 p789 这类多余参数（/jm p123 是合法的单章下载）
    tokens = text.split()
    photo_tokens = [t for t in tokens if re.match(r'^p\d+$', t)]
    if len(tokens) >= 2 and photo_tokens:
        await jm_cmd.finish("格式: /jm <本子ID>\n下载单章请用 /jm p<章节ID>")

    # cooldown
    cooldown_key = f"{event.group_id}:{event.user_id}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    # p prefix → photo download
    if text.startswith("p"):
        photo_id = text[1:]
        if not photo_id.isdigit():
            await jm_cmd.finish("格式: /jm p<章节ID>\n例如: /jm p350234")
        await _download_photo(bot, event, photo_id, cooldown_key)
        return

    # album download
    match = re.search(r"\d+", text)
    if not match:
        await jm_cmd.finish("格式: /jm <本子ID>\n例如: /jm 438516")

    await _download_album(bot, event, match.group(), cooldown_key, fmt)


async def _download_album(bot: Bot, event: GroupMessageEvent, album_id: str, cooldown_key: str, fmt=_DEFAULT_FMT):
    _cleanup_stale_dirs()
    group_id = event.group_id
    loop = asyncio.get_running_loop()
    feature_cls, ext, fmt_name = FORMAT_MAP[fmt]

    def progress(msg: str):
        try:
            asyncio.run_coroutine_threadsafe(
                bot.send_group_msg(group_id=group_id, message=msg),
                loop,
            )
        except Exception:
            pass

    out_path = _make_out_path(album_id, ext)

    usage = shutil.disk_usage(tempfile.gettempdir())
    if usage.free < 500 * 1024 * 1024:
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    client = option.build_jm_client()
    try:
        album = await _run_sync(client.get_album_detail, album_id)
    except JmcomicException as e:
        await jm_cmd.finish(f"❌ 查询失败: {e}")

    tags_str = f"\n🏷️ {'、'.join(album.tags[:5])}" if album.tags else ""
    await jm_cmd.send(
        f"📖 {album.name}\n"
        f"🆔 JM{album.id} | ✍️ {album.author} | 📄 {len(album)}章 🖼️ {album.page_count}页"
        f"{tags_str}"
    )

    if _is_cache_valid(out_path):
        progress(f"📦 命中缓存，直接发送 {fmt_name}……")
        await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)
        return

    quota = await _run_sync(use_download_quota, event.user_id, event.group_id)
    if not quota['ok']:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(quota['msg'])
    progress(quota['msg'])

    progress(f"⏳ 正在下载并生成 {fmt_name}……")

    out_path.unlink(missing_ok=True)

    extra = feature_cls(**{f'{ext}_dir' if ext != 'png' else 'img_dir': str(_TMP_DIR)}, filename_rule='Aid')

    def _dl():
        dler = ProgressJmDownloader(option, progress, fmt_name=fmt_name)
        with dler:
            dler.add_features(extra, 'download_album')
            dler.download_by_album_detail(album)
            dler.raise_if_has_exception()

    try:
        async with _semaphore:
            _cancel_event.clear()
            await _run_sync(_dl, timeout=300)
    except asyncio.TimeoutError:
        _cancel_event.set()
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")
    finally:
        for prefix in ('A', 'P'):
            d = _DL_TMP / f"{prefix}{album_id}"
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    if not out_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ {fmt_name} 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)


async def _download_photo(bot: Bot, event: GroupMessageEvent, photo_id: str, cooldown_key: str):
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

    quota = await _run_sync(use_download_quota, event.user_id, event.group_id)
    if not quota['ok']:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(quota['msg'])
    progress(quota['msg'])

    progress(f"⏳ 正在下载章节并生成 PDF……")

    pdf_path.unlink(missing_ok=True)

    extra = Feature.export_pdf(pdf_dir=str(_TMP_DIR), filename_rule='Pid')

    def _dl():
        dler = ProgressJmDownloader(option, progress)
        with dler:
            dler.add_features(extra, 'download_photo')
            dler.download_by_photo_detail(photo)
            dler.raise_if_has_exception()

    try:
        async with _semaphore:
            _cancel_event.clear()
            await _run_sync(_dl, timeout=120)
    except asyncio.TimeoutError:
        _cancel_event.set()
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")
    finally:
        for prefix in ('A', 'P'):
            d = _DL_TMP / f"{prefix}{photo_id}"
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    if not pdf_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)


_TRANSIT_BASE = "https://transit2.cszxorx.dpdns.org"


async def _upload_to_transit2(file_path: Path, filename: str) -> str:
    loop = asyncio.get_running_loop()

    def _sync():
        size = file_path.stat().st_size

        # 1 — 创建上传会话
        resp = httpx.post(
            f"{_TRANSIT_BASE}/api/upload",
            json={"filename": filename, "size": size, "mimeType": "application/octet-stream"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        file_id = data["fileId"]
        upload_key = data["uploadKey"]
        chunk_urls = data.get("chunkUrls")

        if chunk_urls is None:
            # 2a — 单段上传（<10MB，但此分支实际不会走到）
            upload_url = data["uploadUrl"]
            with open(file_path, "rb") as f:
                r = httpx.put(upload_url, content=f.read(), timeout=300)
            r.raise_for_status()
        else:
            # 2b — 分片上传（>=10MB）
            upload_id = data["uploadId"]
            chunk_size = data["chunkSize"]
            parts = []

            with open(file_path, "rb") as f:
                for i, url in enumerate(chunk_urls):
                    part_number = i + 1
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    r = httpx.put(url, content=chunk, timeout=120)
                    r.raise_for_status()
                    parts.append({"PartNumber": part_number, "ETag": r.headers.get("ETag")})

            # 3 — 完成分片
            r = httpx.post(
                f"{_TRANSIT_BASE}/api/upload/{file_id}/chunks/complete",
                json={"uploadId": upload_id, "uploadKey": upload_key, "parts": parts},
                timeout=30,
            )
            r.raise_for_status()

        return file_id

    return await asyncio.wait_for(
        loop.run_in_executor(None, _sync),
        timeout=600,
    )


async def _upload_and_cleanup(bot: Bot, event: GroupMessageEvent, file_path: Path, id_str: str, cooldown_key: str, ext='pdf', fmt_name='PDF'):
    try:
        try:
            st = file_path.stat()
        except FileNotFoundError:
            _last_use.pop(cooldown_key, None)
            await jm_cmd.finish(f"❌ {fmt_name} 上传失败（文件已被清理），请重新下载")

        if st.st_size > 100 * 1024 * 1024:
            try:
                file_id = await _upload_to_transit2(file_path, f"JM{id_str}.{ext}")
            except Exception as e:
                _last_use.pop(cooldown_key, None)
                await jm_cmd.finish(f"❌ 上传到中转站失败: {e}")

            await jm_cmd.send(
                f"📎 JM{id_str} 文件较大({st.st_size / 1048576:.1f}MB)，已上传至中转站\n"
                f"🔗 {_TRANSIT_BASE}/file/{file_id}\n"
                f"⏰ 24小时自动删除"
            )
            return

        try:
            await bot.call_api(
                "upload_group_file",
                group_id=event.group_id,
                file=str(file_path.resolve()),
                name=f"JM{id_str}.{ext}",
            )
            await jm_cmd.send(f"✅ JM{id_str} 下载完成，{fmt_name} 已发送到群")
        except Exception:
            await jm_cmd.send(f"⚠️ JM{id_str} 正在上传中，请查看群文件")
    finally:
        file_path.unlink(missing_ok=True)
        for prefix in ('A', 'P'):
            d = _DL_TMP / f"{prefix}{id_str}"
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)


async def _handle_rank(bot: Bot, event: GroupMessageEvent, period: str):
    time_param = {"周": "week", "月": "month", "日": "day"}.get(period, "week")

    try:
        option = _get_option()
        client = option.build_jm_client()
        rank_fn = getattr(client, f"{time_param}_ranking")
        page = await _run_sync(rank_fn, 1)
    except Exception as e:
        await jm_cmd.finish(f"❌ 获取排行榜失败: {e}")

    period_cn = {"week": "周", "month": "月", "day": "日"}[time_param]
    results = list(page)[:15]

    lines = [f"🏆 禁漫{period_cn}榜 TOP {len(results)}", ""]
    for idx, (aid, title) in enumerate(results, 1):
        short_title = title if len(title) <= 40 else title[:37] + "..."
        lines.append(f"{idx}. JM{aid}  {short_title}")

    await jm_cmd.finish("\n".join(lines))


async def _handle_random(bot: Bot, event: GroupMessageEvent):
    try:
        option = _get_option()
        client = option.build_jm_client()
        page = await _run_sync(client.month_ranking, 1)
    except Exception as e:
        await jm_cmd.finish(f"❌ 获取推荐失败: {e}")

    results = list(page)
    if not results:
        await jm_cmd.finish("❌ 暂无推荐")

    aid, title = random.choice(results)
    await jm_cmd.finish(f"🎲 今日随机推荐\n\nJM{aid}  {title}\n\n发送 /jm {aid} 下载")
