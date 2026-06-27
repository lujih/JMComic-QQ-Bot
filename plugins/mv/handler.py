import re

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg

from plugins.jm.common import run_sync
from plugins.mv._cmd import mv_cmd
from plugins.mv._search import _search_missav
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

    title, _ = await run_sync(_search_missav, text, timeout=30)

    results, has_next = await run_sync(search_torrent, text, page, timeout=30)

    if not results:
        parts = [f"❌ 未找到 {text} 的磁力链接"]
        if title:
            parts.insert(0, f"📹 {title}")
        await mv_cmd.finish("\n".join(parts))

    lines = []
    if title:
        lines.append(f"📹 {title}")
        lines.append("")

    for i, r in enumerate(results[:5], 1):
        name = r['name']
        if len(name) > 60:
            name = name[:57] + "…"
        lines.append(f"[{i}] {r['size']}  👍{r['seeders']} 👎{r['leechers']}")
        lines.append(r['magnet'])
        lines.append("")

    lines.append("——")
    nav_parts = [f"第{page}页"]
    if page > 1:
        nav_parts.append(f"/mv {text} --page {page - 1} ←")
    if has_next:
        nav_parts.append(f"/mv {text} --page {page + 1} →")
    lines.append("  ".join(nav_parts))

    await mv_cmd.finish("\n".join(lines))
