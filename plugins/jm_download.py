import re
import time
import random
import asyncio
import shutil
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from jmcomic import create_option_by_file, Feature, JmDownloader

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
_last_use: dict[str, float] = {}
_semaphore = asyncio.Semaphore(1)
OPTION_PATH = Path(__file__).parent.parent / "option.yml"
_option_cache = None


def _get_option():
    global _option_cache
    if _option_cache is None:
        _option_cache = create_option_by_file(str(OPTION_PATH))
    return _option_cache


async def _run_sync(func, *args, timeout=180):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args)),
        timeout=timeout,
    )


def _parse_format_flags(text: str):
    fmt = _DEFAULT_FMT
    for flag, name in [('--zip', 'zip'), ('--longimg', 'longimg')]:
        if flag in text:
            fmt = name
            text = text.replace(flag, '').strip()
            break
    return text, fmt


def _is_cache_valid(path: Path, max_age=1800):
    return path.exists() and time.time() - path.stat().st_mtime < max_age


def _check_cooldown(key: str) -> int:
    now = time.time()
    last = _last_use.get(key, 0)
    remaining = COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        return int(remaining)
    _last_use[key] = now
    return 0


HELP_TEXT = (
    "📖 JMComic QQ Bot 命令列表\n\n"
    "/jm <本子ID>            下载本子（默认 PDF）\n"
    "/jm <本子ID> --zip      下载并打包为 ZIP\n"
    "/jm <本子ID> --longimg  下载并拼接为长图\n"
    "/jm p<章节ID>           下载单个章节\n"
    "/jm rank [周/月/日]     查看排行榜（默认周榜）\n"
    "/jm random             随机推荐一本\n"
    "/jm help               显示本帮助\n\n"
    "/jmv <ID>               查看本子详情\n"
    "/jms <关键词>           搜索本子\n"
    "每日早 9:00             自动推送随机推荐到群"
)

class ProgressJmDownloader(JmDownloader):
    def __init__(self, option, progress_cb, photo_count, fmt_name='PDF'):
        super().__init__(option)
        self._cb = progress_cb
        self._photo_count = photo_count
        self._photo_idx = 0
        self._fmt_name = fmt_name

    def _should_report(self, idx):
        total = self._photo_count
        if total <= 5:
            return True
        if idx in (1, total):
            return True
        prev_pct = (idx - 1) * 10 // total
        curr_pct = idx * 10 // total
        return prev_pct != curr_pct

    def before_photo(self, photo):
        super().before_photo(photo)
        self._photo_idx += 1
        if self._should_report(self._photo_idx):
            self._cb(f"📄 [{self._photo_idx}/{self._photo_count}] {photo.name}")

    def after_photo(self, photo):
        super().after_photo(photo)
        if self._should_report(self._photo_idx):
            self._cb(f"✅ 第{self._photo_idx}章完成 ({len(photo)}张图)")

    def after_album(self, album):
        self._cb(f"📄 正在生成 {self._fmt_name}……")
        super().after_album(album)


jm_cmd = on_command("jm", priority=10)


@jm_cmd.handle()
async def handle_jm(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()

    # help
    if text == "help":
        await jm_cmd.finish(HELP_TEXT)

    # rank
    if text.startswith("rank"):
        period = text[4:].strip()
        await _handle_rank(bot, event, period)
        return

    # random
    if text == "random":
        await _handle_random(bot, event)
        return

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
    clean_text, fmt = _parse_format_flags(text)
    match = re.search(r"\d+", clean_text)
    if not match:
        await jm_cmd.finish("格式: /jm <本子ID>\n例如: /jm 438516")

    await _download_album(bot, event, match.group(), cooldown_key, fmt)


async def _download_album(bot: Bot, event: GroupMessageEvent, album_id: str, cooldown_key: str, fmt=_DEFAULT_FMT):
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

    out_path = Path(f"/tmp/jm/{album_id}.{ext}")

    if _is_cache_valid(out_path):
        progress(f"📦 命中缓存，直接发送 {fmt_name}……")
        await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)
        return

    progress(f"⏳ 正在下载 JM{album_id} 并生成 {fmt_name}……")

    out_path.unlink(missing_ok=True)

    usage = shutil.disk_usage("/tmp")
    if usage.free < 500 * 1024 * 1024:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    extra = feature_cls(**{f'{ext}_dir' if ext != 'png' else 'img_dir': '/tmp/jm/'}, filename_rule='Aid')

    def _dl():
        dler = ProgressJmDownloader(option, progress, photo_count=0, fmt_name=fmt_name)
        with dler:
            album = dler.client.get_album_detail(album_id)
            dler._photo_count = len(album)
            dler.add_features(extra, 'download_album')
            dler.download_by_album_detail(album)
            dler.raise_if_has_exception()
        return album, dler

    for attempt in range(2):
        try:
            async with _semaphore:
                await _run_sync(_dl, timeout=300)
            break
        except asyncio.TimeoutError:
            if attempt == 0:
                progress("🔄 下载超时，正在重试……")
                await asyncio.sleep(3)
            else:
                _last_use.pop(cooldown_key, None)
                await jm_cmd.finish("❌ 下载超时，请稍后再试")
        except Exception as e:
            _last_use.pop(cooldown_key, None)
            await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not out_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ {fmt_name} 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, out_path, album_id, cooldown_key, ext, fmt_name)


async def _download_photo(bot: Bot, event: GroupMessageEvent, photo_id: str, cooldown_key: str):
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

    progress(f"⏳ 正在下载章节 p{photo_id} 并生成 PDF……")

    pdf_path = Path(f"/tmp/jm/{photo_id}.pdf")
    pdf_path.unlink(missing_ok=True)

    usage = shutil.disk_usage("/tmp")
    if usage.free < 500 * 1024 * 1024:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    option = _get_option()
    extra = Feature.export_pdf(pdf_dir="/tmp/jm/", filename_rule='Pid')

    def _dl():
        dler = ProgressJmDownloader(option, progress, photo_count=1)
        with dler:
            photo = dler.client.get_photo_detail(photo_id)
            dler.add_features(extra, 'download_photo')
            dler.download_by_photo_detail(photo)
            dler.raise_if_has_exception()
        return photo, dler

    for attempt in range(2):
        try:
            async with _semaphore:
                await _run_sync(_dl, timeout=120)
            break
        except asyncio.TimeoutError:
            if attempt == 0:
                progress("🔄 下载超时，正在重试……")
                await asyncio.sleep(3)
            else:
                _last_use.pop(cooldown_key, None)
                await jm_cmd.finish("❌ 下载超时，请稍后再试")
        except Exception as e:
            _last_use.pop(cooldown_key, None)
            await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not pdf_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)


async def _upload_and_cleanup(bot: Bot, event: GroupMessageEvent, file_path: Path, id_str: str, cooldown_key: str, ext='pdf', fmt_name='PDF'):
    if file_path.stat().st_size > 100 * 1024 * 1024:
        file_path.unlink(missing_ok=True)
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ {fmt_name} 超过 100MB，无法发送到群\n💡 试试 /jm {id_str} --zip 压缩后更小")

    for attempt in range(2):
        try:
            await bot.call_api(
                "upload_group_file",
                group_id=event.group_id,
                file=str(file_path.resolve()),
                name=f"JM{id_str}.{ext}",
            )
            await jm_cmd.send(f"✅ JM{id_str} 下载完成，{fmt_name} 已发送到群")
            return
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                user_id = event.user_id
                try:
                    await bot.send_private_msg(
                        user_id=user_id,
                        message=f"JM{id_str} 下载已完成，但群文件上传失败: {e}\n"
                                f"请在群内重试，或尝试 /jm {id_str} --zip",
                    )
                except Exception:
                    pass
                await jm_cmd.send(f"❌ {fmt_name} 上传失败: {e}")
    finally:
        file_path.unlink(missing_ok=True)
        dl_dir = Path(f"/tmp/jm_dl/A{id_str}")
        if dl_dir.exists():
            shutil.rmtree(dl_dir, ignore_errors=True)


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
