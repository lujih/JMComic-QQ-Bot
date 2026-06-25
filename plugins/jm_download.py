import re
import time
import random
import asyncio
import shutil
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

import jmcomic
from jmcomic import create_option_by_file, Feature

__plugin_name__ = "jm_download"
__plugin_usage__ = (
    "/jm <ID> — 下载本子\n"
    "/jm p<ID> — 下载单章\n"
    "/jm rank [周/月/日] — 排行榜\n"
    "/jm random — 随机一本"
)

COOLDOWN_SECONDS = 60
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
    "/jm <本子ID>        下载本子并发送 PDF\n"
    "/jm p<章节ID>       下载单个章节\n"
    "/jm rank [周/月/日]  查看排行榜（默认周榜）\n"
    "/jm random          随机推荐一本\n"
    "/jm help            显示本帮助\n\n"
    "/jmv <ID>           查看本子详情\n"
    "/jms <关键词>       搜索本子"
)

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
    match = re.search(r"\d+", text)
    if not match:
        await jm_cmd.finish("格式: /jm <本子ID>\n例如: /jm 438516")

    await _download_album(bot, event, match.group(), cooldown_key)


async def _download_album(bot: Bot, event: GroupMessageEvent, album_id: str, cooldown_key: str):
    await jm_cmd.send(f"⏳ 正在下载 JM{album_id} 并生成 PDF……")

    pdf_path = Path(f"/tmp/jm/{album_id}.pdf")
    pdf_path.unlink(missing_ok=True)

    # check disk space
    usage = shutil.disk_usage("/tmp")
    if usage.free < 500 * 1024 * 1024:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    try:
        option = _get_option()
        async with _semaphore:
            await _run_sync(jmcomic.download_album, album_id, option, timeout=300)
    except asyncio.TimeoutError:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not pdf_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, album_id, cooldown_key)


async def _download_photo(bot: Bot, event: GroupMessageEvent, photo_id: str, cooldown_key: str):
    await jm_cmd.send(f"⏳ 正在下载章节 p{photo_id} 并生成 PDF……")

    pdf_path = Path(f"/tmp/jm/{photo_id}.pdf")
    pdf_path.unlink(missing_ok=True)

    usage = shutil.disk_usage("/tmp")
    if usage.free < 500 * 1024 * 1024:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 服务器磁盘空间不足，请稍后再试")

    try:
        option = _get_option()
        extra = Feature.export_pdf(pdf_dir="/tmp/jm/")
        async with _semaphore:
            await _run_sync(
                lambda: jmcomic.download_photo(photo_id, option, extra=extra),
                timeout=120,
            )
    except asyncio.TimeoutError:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ 下载超时，请稍后再试")
    except Exception as e:
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish(f"❌ 下载失败: {type(e).__name__}: {e}")

    if not pdf_path.exists():
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 生成失败，文件未找到")

    await _upload_and_cleanup(bot, event, pdf_path, photo_id, cooldown_key)


async def _upload_and_cleanup(bot: Bot, event: GroupMessageEvent, pdf_path: Path, id_str: str, cooldown_key: str):
    if pdf_path.stat().st_size > 100 * 1024 * 1024:
        pdf_path.unlink(missing_ok=True)
        _last_use.pop(cooldown_key, None)
        await jm_cmd.finish("❌ PDF 超过 100MB，无法发送到群")

    try:
        await bot.call_api(
            "upload_group_file",
            group_id=event.group_id,
            file=str(pdf_path.resolve()),
            name=f"JM{id_str}.pdf",
        )
        await jm_cmd.send(f"✅ JM{id_str} 下载完成，PDF 已发送到群")
    except Exception as e:
        await jm_cmd.send(f"PDF 文件已生成但发送失败: {e}\n可联系管理员手动获取")
    finally:
        pdf_path.unlink(missing_ok=True)
        dl_dir = Path(f"/tmp/jm_dl/{id_str}")
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
