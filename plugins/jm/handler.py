import re
import random as _random

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

from plugins._option import get_option as _get_option
from plugins.jm._cmd import jm_cmd
from plugins.jm.common import (
    _parse_format_flags,
    _check_cooldown,
    _run_sync,
    HELP_TEXT,
)
from plugins.jm.album import _download_album
from plugins.jm.photo import _download_photo


@jm_cmd.handle()
async def handle_jm(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()

    try:
        text, fmt = _parse_format_flags(text)
    except ValueError as e:
        await jm_cmd.finish(f"❌ {e}")

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

    cooldown_key = f"{event.group_id}:{event.user_id}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jm_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    if text.startswith("p"):
        photo_id = text[1:]
        if not photo_id.isdigit():
            await jm_cmd.finish("格式: /jm p<章节ID>\n例如: /jm p350234")
        await _download_photo(bot, event, photo_id, cooldown_key)
        return

    match = re.search(r"\d+", text)
    if not match:
        await jm_cmd.finish("格式: /jm <本子ID>\n例如: /jm 438516")

    await _download_album(bot, event, match.group(), cooldown_key, fmt)


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

    aid, title = _random.choice(results)
    await jm_cmd.finish(f"🎲 今日随机推荐\n\nJM{aid}  {title}\n\n发送 /jm {aid} 下载")
