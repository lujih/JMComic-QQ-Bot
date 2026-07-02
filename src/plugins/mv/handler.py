import asyncio
import os
import re

import httpx
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from jmcomic import jm_log

from _common import run_sync
from plugins.mv.cmd import mv_cmd
from plugins.mv._search import search_video
from plugins.mv._torrent import search as search_torrent


def _clean_magnet(magnet: str) -> str:
    """去掉 &tr= tracker 参数，保留 xt=/dn=，使磁链短而整洁"""
    parts = magnet.split('&')
    return '&'.join(p for p in parts if not p.startswith('tr='))


@mv_cmd.handle()
async def handle_mv(bot: Bot, event: GroupMessageEvent, msg: Message = CommandArg()):
    text = msg.extract_plain_text().strip()

    if not text:
        await mv_cmd.finish(
            "格式: /mv <番号>\n"
            "示例: /mv SSNI-123\n"
            "      /mv SSNI-123 --page 2"
        )

    page = 1
    m = re.search(r'--page\s+(\d+)', text)
    if m:
        page = int(m.group(1))
        text = re.sub(r'--page\s+\d+', '', text).strip()
        if page < 1:
            page = 1

    av_info = await run_sync(search_video, text, timeout=30)
    if not av_info:
        await mv_cmd.finish(f"❌ 未找到 {text.upper()} 的信息")

    async def _delayed_rm(path: str, delay: int = 30):
        await asyncio.sleep(delay)
        try:
            os.remove(path)
        except OSError:
            pass

    cover_path = None
    if img_url := av_info.get('cover'):
        try:
            resp = await run_sync(
                httpx.get, img_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"},
                timeout=10,
            )
            safe = re.sub(r'\W', '_', text)
            cover_path = f"/tmp/jm_mv_cover_{safe}.jpg"
            with open(cover_path, "wb") as f:
                f.write(resp.content)
            await mv_cmd.send(Message(f"[CQ:image,file=file://{cover_path}]"))
            asyncio.create_task(_delayed_rm(cover_path))
        except Exception:
            await mv_cmd.send("❌ 封面下载失败")
    else:
        await mv_cmd.send("❌ 无封面图")

    # Message 2: 元信息
    meta_lines = []
    display_title = av_info.get('title', text.upper())
    if len(display_title) > 80:
        display_title = display_title[:77] + "…"
    meta_lines.append(f"📹 {display_title}")

    if av_info.get('actresses'):
        meta_lines.append(f"🎬 女優: {' '.join(av_info['actresses'])}")
    if av_info.get('date'):
        meta_lines.append(f"📅 日期: {av_info['date']}")
    if av_info.get('studio'):
        meta_lines.append(f"🏢 制作商: {av_info['studio']}")
    if av_info.get('duration'):
        meta_lines.append(f"⏱ 时长: {av_info['duration']}")

    await mv_cmd.send("\n".join(meta_lines))

    # Message 3: 磁链汇总
    try:
        results, has_next = await run_sync(search_torrent, text, page, timeout=30)
    except Exception as e:
        jm_log('jm.mv.torrent', f"sukebei 搜索失败: {e}")
        await mv_cmd.finish("❌ 磁力搜索失败，请稍后再试")

    if not results:
        results = av_info.get('magnets')

    if not results:
        await mv_cmd.finish(f"❌ 未找到 {text.upper()} 的磁力链接")

    lines = []
    for i, r in enumerate(results[:5], 1):
        magnet = _clean_magnet(r['magnet'])
        size = r.get('size', '')
        seeders = r.get('seeders', 0)
        leechers = r.get('leechers', 0)

        if size:
            warning = ""
            if seeders == 0:
                warning = "  ⚠️死種"
            elif leechers >= seeders * 5 and seeders > 0:
                warning = "  ⚠️低存活"
            lines.append(f"{i}. {size}  👍{seeders} 👎{leechers}{warning}")
            lines.append(f"   {magnet}")
        else:
            lines.append(f"{i}. {magnet}")

    if page > 1 or has_next:
        lines.append("")
        nav_parts = [f"第{page}页"]
        if page > 1:
            nav_parts.append(f"/mv {text} --page {page - 1} ←")
        if has_next:
            nav_parts.append(f"/mv {text} --page {page + 1} →")
        lines.append("——")
        lines.append("  ".join(nav_parts))

    await mv_cmd.finish("\n".join(lines))
