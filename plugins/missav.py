import re
import asyncio
import cloudscraper
from bs4 import BeautifulSoup

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import is_type

from plugins._missav_torrent import search as search_torrent

__plugin_name__ = "missav"
__plugin_usage__ = (
    "/mv <番号> — 搜索番号并返回磁力链接\n"
    "/mv <关键词> — 搜索关键词\n"
    "/mv <番号> --page N — 翻页"
)

mv_cmd = on_command("mv", priority=10, rule=is_type(GroupMessageEvent))

MISSAV_SEARCH = "https://missav.ai/search/{query}"

_scraper = None


def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=10,
        )
    return _scraper


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

    title, _ = await _run_sync(_search_missav, text)

    results, has_next = await _run_sync(search_torrent, text, page)

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


def _search_missav(query: str):
    from urllib.parse import quote
    url = MISSAV_SEARCH.format(query=quote(query, safe=''))

    try:
        resp = _get_scraper().get(url, timeout=20)
    except Exception:
        return "", ""

    if resp.status_code != 200:
        return "", ""

    try:
        soup = BeautifulSoup(resp.content, 'html.parser')
        cards = soup.select('div.thumbnail')
        if not cards:
            return "", ""

        # 尝试在结果中匹配番号
        query_upper = query.upper()
        for card in cards[:10]:
            img = card.select_one('img')
            if img and img.get('alt', ''):
                alt = img['alt'].strip()
                if alt and query_upper in alt.upper():
                    thumbnail = (img.get('data-src', '') or img.get('src', '') or '')
                    return alt, thumbnail

        # 回退：取第一个结果
        first = cards[0]
        img = first.select_one('img')
        if img and img.get('alt', ''):
            thumbnail = (img.get('data-src', '') or img.get('src', '') or '')
            return img['alt'].strip(), thumbnail
    except Exception:
        pass

    return "", ""


async def _run_sync(func, *args, timeout=30):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args)),
        timeout=timeout,
    )
