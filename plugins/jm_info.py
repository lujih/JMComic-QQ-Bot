import re
import asyncio
import itertools
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

from jmcomic import create_option_by_file

__plugin_name__ = "jm_info"
__plugin_usage__ = "/jmv <ID> — 查看本子详情\n/jms <关键字> — 搜索本子"

OPTION_PATH = Path(__file__).parent.parent / "option.yml"
_option_cache = create_option_by_file(str(OPTION_PATH))


def _get_option():
    return _option_cache


async def _run_sync(func, *args, timeout=30):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args)),
        timeout=timeout,
    )


jmv_cmd = on_command("jmv", priority=10)
jms_cmd = on_command("jms", priority=10)


@jmv_cmd.handle()
async def handle_jmv(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    match = re.search(r"\d+", text)
    if not match:
        await jmv_cmd.finish("格式: /jmv <本子ID>\n例如: /jmv 438516")

    album_id = match.group()
    await jmv_cmd.send(f"🔍 正在查询 JM{album_id} 详情……")

    try:
        option = _get_option()
        client = option.build_jm_client()
        album = await _run_sync(client.get_album_detail, album_id)
    except asyncio.TimeoutError:
        await jmv_cmd.finish("❌ 查询超时，请稍后再试")
    except Exception as e:
        await jmv_cmd.finish(f"❌ 查询失败: {e}")

    tags_str = "、".join(album.tags) if album.tags else "无"
    lines = [
        f"📖 {album.name}",
        f"🆔 JM{album.id}",
        f"✍️ 作者: {album.author}",
        f"📄 章节数: {len(album)}",
        f"🖼️ 总页数: {album.page_count}",
        f"🏷️ 标签: {tags_str}",
    ]
    if album.comment_count:
        lines.append(f"💬 评论: {album.comment_count}")

    await jmv_cmd.finish("\n".join(lines))


@jms_cmd.handle()
async def handle_jms(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    if not text:
        await jms_cmd.finish("格式: /jms <关键词>\n例如: /jms 无修正")

    await jms_cmd.send(f"🔍 正在搜索「{text}」……")

    try:
        option = _get_option()
        client = option.build_jm_client()
        page = await _run_sync(client.search_site, text, 1)
    except asyncio.TimeoutError:
        await jms_cmd.finish("❌ 搜索超时，请稍后再试")
    except Exception as e:
        await jms_cmd.finish(f"❌ 搜索失败: {e}")

    results = list(itertools.islice(page, 10))
    if not results:
        await jms_cmd.finish("❌ 未找到相关结果")

    lines = [f"🔍 「{text}」搜索结果 (共{page.total}条):", ""]
    for aid, title in results:
        short_title = title if len(title) <= 50 else title[:47] + "..."
        lines.append(f"JM{aid}  {short_title}")

    if page.total > len(results):
        lines.append(f"\n... 还有 {page.total - len(results)} 条未显示")

    await jms_cmd.finish("\n".join(lines))
