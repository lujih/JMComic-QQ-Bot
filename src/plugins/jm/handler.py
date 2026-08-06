import re
import asyncio
import random as _random

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

from jmcomic import jm_log
from jm_option import get_option as _get_option
from plugins.jm.cmd import jm_cmd

from plugins.jm.common import (
    _parse_format_flags,
    _check_cooldown,
    _clear_cooldown,
    _is_dup_message,
    _DEFAULT_FMT,
    HELP_TEXT,
)
from plugins.jm.album import _download_album
from plugins.jm.photo import _download_photo


@jm_cmd.handle()
async def handle_jm(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    if event.user_id == int(bot.self_id):
        return

    if _is_dup_message(event.message_id):
        jm_log('jm.handler', f'忽略重复消息 message_id={event.message_id}')
        return

    text = msg.extract_plain_text().strip()

    try:
        text, fmt = _parse_format_flags(text)
    except ValueError as e:
        jm_log('jm.handler', '格式解析错误', e)
        await jm_cmd.finish("❌ 格式错误，请检查参数")

    if text == "help":
        await jm_cmd.finish(HELP_TEXT)

    match = re.match(r'^rank\s*(\S*)$', text)
    if match:
        period = match.group(1).strip()
        await _handle_rank(bot, event, period)
        return

    if text == "random":
        await _handle_random(bot, event)
        return

    tokens = text.split()
    photo_tokens = [t for t in tokens if re.match(r'^p\d+$', t)]
    if len(tokens) >= 2 and photo_tokens:
        await jm_cmd.finish("格式: /jm <本子ID>\n下载单章请用 /jm p<章节ID>")

    if text.startswith("p"):
        if fmt != _DEFAULT_FMT:
            await jm_cmd.finish("单章下载仅支持 PDF 格式，请移除 --zip/--longimg")
        if not re.fullmatch(r"p\d+", text):
            await jm_cmd.finish("格式: /jm p<章节ID>\n例如: /jm p350234")
        photo_id = text[1:]
        cooldown_key = f"{event.user_id}:p{photo_id}"
        remaining = _check_cooldown(cooldown_key)
        if remaining:
            await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")
        await _download_photo(bot, event, photo_id, cooldown_key)
        return

    if not re.fullmatch(r"\d+", text):
        await jm_cmd.finish("格式: /jm <本子ID>\n例如: /jm 438516\n更多: /jm help")

    album_id = text
    cooldown_key = f"{event.user_id}:{album_id}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")
    await _download_album(bot, event, album_id, cooldown_key, fmt)


async def _handle_rank(bot: Bot, event: GroupMessageEvent, period: str):
    time_param = {"周": "week", "月": "month", "日": "day"}.get(period, "week")
    cooldown_key = f"{event.user_id}:rank:{time_param}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    try:
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            rank_fn = getattr(cl, f"{time_param}_ranking")
            page = await asyncio.wait_for(rank_fn(1), timeout=60)
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        jm_log('jm.handler', f'获取排行榜超时: {time_param}')
        await jm_cmd.finish("❌ 查询超时，请稍后再试")
    except Exception as e:
        jm_log('jm.handler', '获取排行榜失败', e)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 获取排行榜失败")

    period_cn = {"week": "周", "month": "月", "day": "日"}[time_param]
    results = list(page)[:15]

    lines = [f"🏆 禁漫{period_cn}榜 TOP {len(results)}", ""]
    for idx, (aid, title) in enumerate(results, 1):
        short_title = title if len(title) <= 40 else title[:37] + "..."
        lines.append(f"{idx}. JM{aid}  {short_title}")

    await jm_cmd.finish("\n".join(lines))


async def _handle_random(bot: Bot, event: GroupMessageEvent):
    cooldown_key = f"{event.user_id}:random"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    try:
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            page = await asyncio.wait_for(cl.month_ranking(1), timeout=30)
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        jm_log('jm.handler', '获取推荐超时')
        await jm_cmd.finish("❌ 查询超时，请稍后再试")
    except Exception as e:
        jm_log('jm.handler', '获取推荐失败', e)
        _clear_cooldown(cooldown_key)
        await jm_cmd.finish("❌ 获取推荐失败")

    results = list(page)
    if not results:
        await jm_cmd.finish("❌ 暂无推荐")

    aid, title = _random.choice(results)
    await jm_cmd.finish(f"🎲 今日随机推荐\n\nJM{aid}  {title}\n\n发送 /jm {aid} 下载")
