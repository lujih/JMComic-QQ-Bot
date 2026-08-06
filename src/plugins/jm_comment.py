import re
import asyncio

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import is_type

from jmcomic import jm_log
from jmcomic.jm_exception import RequestRetryAllFailException

from jm_option import get_option as _get_option
from plugins.jm.common import _check_cooldown, _clear_cooldown

__plugin_name__ = "jm_comment"
__plugin_usage__ = "/jmc <ID> [页码] — 查看本子评论"

jmc_cmd = on_command("jmc", priority=10, rule=is_type(GroupMessageEvent))

_MAX_MAIN_COMMENTS = 8
_CONTENT_LIMIT = 60
_REPLY_LIMIT = 40


def _clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def _comment_title(comment) -> str:
    name = comment.nickname or comment.username or "匿名"
    parts = [name]
    if comment.likes:
        parts.append(f"👍{comment.likes}")
    if comment.created_at:
        parts.append(str(comment.created_at))
    if comment.is_spoiler:
        parts.append("⚠️剧透")
    return " · ".join(parts)


def _comment_lines(comment) -> list[str]:
    lines = [_comment_title(comment)]
    content = _clean_text(comment.content)
    if content:
        lines.append(content[:_CONTENT_LIMIT] + ("…" if len(content) > _CONTENT_LIMIT else ""))
    for reply in comment.replies[:2]:
        rname = reply.nickname or reply.username or "匿名"
        rtext = _clean_text(reply.content)
        if not rtext:
            continue
        rtext = rtext[:_REPLY_LIMIT] + ("…" if len(rtext) > _REPLY_LIMIT else "")
        lines.append(f"  └ {rname}：{rtext}")
    return lines


@jmc_cmd.handle()
async def handle_jmc(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    m = re.search(r"(\d+)", text)
    if not m:
        await jmc_cmd.finish("格式: /jmc <本子ID> [页码]\n例如: /jmc 438516\n      /jmc 438516 2")

    album_id = m.group()
    rest = text[m.end():].strip()
    m2 = re.search(r"(\d+)", rest)
    page = max(int(m2.group()), 1) if m2 else 1

    cooldown_key = f"{event.user_id}:jmc:{album_id}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await jmc_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    try:
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            page_data = await asyncio.wait_for(
                cl.album_pagination(album_id, page), timeout=60
            )
    except asyncio.TimeoutError:
        _clear_cooldown(cooldown_key)
        jm_log('jm.comment', f'获取评论超时: {album_id} p{page}')
        await jmc_cmd.finish("❌ 查询超时，请稍后再试")
    except RequestRetryAllFailException:
        _clear_cooldown(cooldown_key)
        jm_log('jm.comment', f'获取评论失败: API 不可达 ({album_id})')
        await jmc_cmd.finish("❌ 查询失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log('jm.comment', f'获取评论失败: {album_id}', e)
        await jmc_cmd.finish("❌ 查询失败")

    comments = list(page_data)[:_MAX_MAIN_COMMENTS]
    if not comments:
        await jmc_cmd.finish("❌ 暂无评论")

    total = page_data.total or 0
    page_count = page_data.page_count or 1
    lines = [f"💬 JM{album_id} 评论" + (f"（共 {total} 条）" if total else "") + f"｜第 {page}/{page_count} 页", ""]
    for idx, comment in enumerate(comments, 1):
        lines.append(f"{idx}. " + "\n   ".join(_comment_lines(comment)))
        lines.append("")

    if page_count > 1:
        nav = []
        if page > 1:
            nav.append(f"/jmc {album_id} {page - 1} ←")
        if page < page_count:
            nav.append(f"/jmc {album_id} {page + 1} →")
        if nav:
            lines.append("——")
            lines.append("  ".join(nav))

    await jmc_cmd.finish("\n".join(lines))
