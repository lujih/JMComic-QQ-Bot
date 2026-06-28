import re

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

from plugins.jm.common import run_sync
from plugins.mv._cmd import mv_cmd
from plugins.mv._search import _search_missav, _fetch_av_detail
from plugins.mv._torrent import search as search_torrent


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

    await mv_cmd.send(f"🔍 正在搜索 {text}……")

    title, cover, detail_url = await run_sync(_search_missav, text, timeout=30)

    info_lines = []
    display_title = title or text.upper()
    if len(display_title) > 80:
        display_title = display_title[:77] + "…"
    info_lines.append(f"📹 {display_title}")

    if detail_url:
        av_info = await run_sync(_fetch_av_detail, detail_url, timeout=30)
        if av_info.get('actresses'):
            info_lines.append(f"🎬 女优: {' '.join(av_info['actresses'])}")
        if av_info.get('date'):
            info_lines.append(f"📅 日期: {av_info['date']}")
        if av_info.get('duration'):
            info_lines.append(f"⏱ 时长: {av_info['duration']}")
        if av_info.get('studio'):
            info_lines.append(f"🏢 制作商: {av_info['studio']}")
        img_url = av_info.get('cover') or cover
        if img_url:
            info_lines.append(f"[CQ:image,file={img_url}]")

    await mv_cmd.send("\n".join(info_lines))

    results, has_next = await run_sync(search_torrent, text, page, timeout=30)

    if not results:
        await mv_cmd.finish(f"❌ 未找到 {text} 的磁力链接")

    lines = []
    for i, r in enumerate(results[:5], 1):
        name = r['name']
        if len(name) > 90:
            name = name[:87] + "…"

        seeders = r['seeders']
        leechers = r['leechers']

        warning = ""
        if seeders == 0:
            warning = "  ⚠️死種"
        elif leechers >= seeders * 5 and seeders > 0:
            warning = "  ⚠️低存活"

        magnet = r['magnet']
        if '&' in magnet:
            magnet = magnet.split('&')[0]

        lines.append(f"[{i}] {name}")
        lines.append(f"    {r['size']}  👍{seeders} 👎{leechers}{warning}")
        lines.append(f"    {magnet}")

    lines.append("")
    nav_parts = [f"第{page}页"]
    if page > 1:
        nav_parts.append(f"/mv {text} --page {page - 1} ←")
    if has_next:
        nav_parts.append(f"/mv {text} --page {page + 1} →")
    lines.append("——")
    lines.append("  ".join(nav_parts))

    await mv_cmd.finish("\n".join(lines))
