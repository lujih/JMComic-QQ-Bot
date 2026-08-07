import os
import re
import asyncio
import itertools
import tempfile
import uuid
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import is_type

from jmcomic import jm_log, JmcomicText
from jmcomic.jm_exception import MissingAlbumPhotoException, RequestRetryAllFailException

from jm_option import get_option as _get_option

__plugin_name__ = "jm_info"
__plugin_usage__ = "/jmv <ID> — 查看本子详情\n/jms <关键字> — 搜索本子"


jmv_cmd = on_command("jmv", priority=10, rule=is_type(GroupMessageEvent))
jms_cmd = on_command("jms", priority=10, rule=is_type(GroupMessageEvent))


async def _delayed_rm(path: str, delay: int = 30):
    await asyncio.sleep(delay)
    try:
        os.remove(path)
    except Exception:
        pass


async def _fetch_cover(cl, album_id: str) -> str | None:
    """下载本子封面到临时文件，失败返回 None（静默降级为纯文本详情）"""
    try:
        cover_url = JmcomicText.get_album_cover_url(album_id)
        img = await asyncio.wait_for(cl.get_jm_image(cover_url), timeout=30)
        if img.http_code != 200 or not img.content:
            return None
        path = str(Path(tempfile.gettempdir()) / f"jm_cover_{album_id}_{uuid.uuid4().hex[:8]}.jpg")
        with open(path, "wb") as f:
            f.write(img.content)
        return path
    except Exception as e:
        jm_log('jm.info', f'封面下载失败: {album_id}', e)
        return None


@jmv_cmd.handle()
async def handle_jmv(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    match = re.search(r"\d+", text)
    if not match:
        await jmv_cmd.finish("格式: /jmv <本子ID>\n例如: /jmv 438516")

    album_id = match.group()
    await jmv_cmd.send(f"🔍 正在查询 JM{album_id} 详情……")

    cover_path = None
    try:
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            album = await asyncio.wait_for(cl.get_album_detail(album_id), timeout=60)
            cover_path = await _fetch_cover(cl, album_id)
    except asyncio.TimeoutError:
        jm_log('jm.info', f'查询详情超时: {album_id}')
        await jmv_cmd.finish("❌ 查询超时，请稍后再试")
    except MissingAlbumPhotoException:
        jm_log('jm.info', f'本子不存在: {album_id}')
        await jmv_cmd.finish("❌ 本子不存在，请检查 ID")
    except RequestRetryAllFailException:
        jm_log('jm.info', f'查询详情失败: API 不可达 ({album_id})')
        await jmv_cmd.finish("❌ 查询失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        jm_log('jm.info', '查询详情失败', e)
        await jmv_cmd.finish("❌ 查询失败")

    if cover_path:
        await jmv_cmd.send(Message(f"[CQ:image,file=file://{cover_path}]"))
        asyncio.create_task(_delayed_rm(cover_path))

    tags_str = "、".join(album.tags) if album.tags else "无"
    lines = [
        f"📖 {album.oname or album.name}",
        f"🆔 JM{album.id}",
        f"✍️ 作者: {'、'.join(album.authors) if album.authors else 'N/A'}",
        f"📄 章节数: {len(album)}",
        f"🖼️ 总页数: {album.page_count or '?'}",
    ]
    if album.description and album.description != 'None':
        desc = re.sub(r'\s+', ' ', album.description).strip()
        lines.append(f"📝 简介: {desc[:100]}{'…' if len(desc) > 100 else ''}")
    if album.comment_count:
        lines.append(f"💬 评论: {album.comment_count}")

    if album.pub_date and album.pub_date != '0':
        lines.append(f"📅 发布日期: {album.pub_date}")
    if album.update_date and album.update_date != '0':
        lines.append(f"📅 更新日期: {album.update_date}")
    if album.views:
        lines.append(f"👀 观看: {album.views}")
    if album.likes:
        lines.append(f"❤️ 点赞: {album.likes}")

    lines.append(f"🏷️ 标签: {tags_str}")

    if album.actors:
        lines.append(f"🎭 人物: {'、'.join(album.actors)}")
    if album.works:
        lines.append(f"📚 作品: {'、'.join(album.works)}")

    if len(album) > 0:
        chapter_lines = []
        for pid, pindex, pname in itertools.islice(album.episode_list, 30):
            chapter_lines.append(f"    第{pindex}話 {pname} (id: {pid})")
        lines.append(f"\n📑 章节 ({len(album)}):")
        lines.extend(chapter_lines)
        if len(album) > 30:
            lines.append(f"    … 还有 {len(album) - 30} 章未显示（用 /jm 直接下载）")

    related = getattr(album, 'related_list', None) or []
    if related:
        lines.append("\n📚 相关推荐:")
        for r in itertools.islice(related, 5):
            rid = r.get('id', '')
            rname = r.get('name', '')
            if not rid:
                continue
            rname = rname if len(rname) <= 30 else rname[:27] + "…"
            lines.append(f"JM{rid}  {rname}")

    await jmv_cmd.finish("\n".join(lines))


@jms_cmd.handle()
async def handle_jms(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()
    if not text:
        await jms_cmd.finish("格式: /jms <关键词>\n例如: /jms 无修正")

    await jms_cmd.send(f"🔍 正在搜索「{text}」……")

    try:
        option = _get_option()
        async with option.new_jm_async_client() as cl:
            page = await asyncio.wait_for(cl.search_site(text, 1), timeout=60)
    except asyncio.TimeoutError:
        jm_log('jm.info', f'搜索超时: {text}')
        await jms_cmd.finish("❌ 搜索超时，请稍后再试")
    except RequestRetryAllFailException:
        jm_log('jm.info', f'搜索失败: API 不可达 ({text})')
        await jms_cmd.finish("❌ 搜索失败，API 暂时不可达，请稍后再试")
    except Exception as e:
        jm_log('jm.info', '搜索失败', e)
        await jms_cmd.finish("❌ 搜索失败")

    results = list(itertools.islice(page, 10))
    if not results:
        await jms_cmd.finish("❌ 未找到相关结果")

    total = getattr(page, 'total', len(results))
    lines = [f"🔍 「{text}」搜索结果 (共{total}条):", ""]
    for aid, title in results:
        short_title = title if len(title) <= 50 else title[:47] + "..."
        lines.append(f"JM{aid}  {short_title}")

    if total > len(results):
        lines.append(f"\n... 还有 {total - len(results)} 条未显示")

    await jms_cmd.finish("\n".join(lines))
