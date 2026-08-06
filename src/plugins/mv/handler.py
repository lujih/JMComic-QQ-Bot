import asyncio
import os
import re
import tempfile
from pathlib import Path

import httpx
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from jmcomic import jm_log

from _common import run_sync
from plugins.jm.common import _check_cooldown, _clear_cooldown
from plugins.mv.cmd import mv_cmd
from plugins.mv._search import search_video, _btih, _normalize_code
from plugins.mv._torrent import search as search_torrent

# 限制同时存活的 Chromium 数（每命令 MissAV/JavDB 各拉起 1 个 headless 浏览器）
_mv_search_semaphore = asyncio.Semaphore(2)


def _clean_magnet(magnet: str, short_id: str = "") -> str:
    """磁链清洗：去掉 &tr= tracker，dn= 替换为短番号（如 MDBK-331）"""
    parts = magnet.split('&')
    kept = []
    for p in parts:
        if p.startswith('tr='):
            continue
        if p.startswith('dn=') and short_id:
            orig = p.split('=', 1)[1]
            ext = ".mp4" if orig.endswith(".mp4") else ""
            kept.append(f"dn={short_id}{ext}")
            continue
        kept.append(p)
    return '&'.join(kept)


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

    cooldown_key = f"{event.user_id}:mv:{_normalize_code(text)}:{page}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await mv_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    try:
        async with _mv_search_semaphore:
            av_info = await run_sync(search_video, text, timeout=120)
    except Exception as e:
        _clear_cooldown(cooldown_key)
        jm_log('jm.mv.search', '视频搜索异常', e)
        await mv_cmd.finish(f"❌ 搜索 {text.upper()} 时出现异常，请稍后再试")
    if not av_info:
        _clear_cooldown(cooldown_key)
        await mv_cmd.finish(f"❌ 未找到 {text.upper()} 的信息")

    async def _delayed_rm(path: str, delay: int = 30):
        await asyncio.sleep(delay)
        try:
            os.remove(path)
        except Exception:
            pass

    cover_path = None
    if img_url := av_info.get('cover'):
        resp = None
        try:
            resp = await run_sync(
                lambda: httpx.get(img_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                }, timeout=10, follow_redirects=True),
                timeout=30,
            )
            if resp.status_code != 200:
                raise ValueError(f"封面下载状态码 {resp.status_code}")
            safe = re.sub(r'\W', '_', text)
            import uuid
            cover_path = str(Path(tempfile.gettempdir()) / f"jm_mv_cover_{safe}_{uuid.uuid4().hex[:8]}.jpg")
            with open(cover_path, "wb") as f:
                f.write(resp.content)
            await mv_cmd.send(Message(f"[CQ:image,file=file://{cover_path}]"))
            asyncio.create_task(_delayed_rm(cover_path))
        except Exception as e:
            jm_log('jm.mv.cover', f'封面下载失败', e)
            if cover_path and os.path.exists(cover_path):
                os.remove(cover_path)
            await mv_cmd.send("❌ 封面下载失败")
        finally:
            if resp is not None:
                resp.close()
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
        m = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', av_info['date'])
        meta_lines.append(f"📅 日期: {m.group() if m else av_info['date']}")
    if av_info.get('studio'):
        meta_lines.append(f"🏢 制作商: {av_info['studio']}")
    if av_info.get('duration'):
        m = re.split(r'[:,]', av_info['duration'])
        meta_lines.append(f"⏱ 时长: {m[0].strip() if len(m) > 0 else av_info['duration']}")

    await mv_cmd.send("\n".join(meta_lines))

    # Message 3: 磁链汇总
    # 多格式搜索 sukebei：原始（PRED-485）/去分隔（pred485）/无短横时反推标准格式，并行搜索后按 BTIH 去重合并
    has_next = False
    results = []
    seen_btih = set()
    queries = [text.strip(), re.sub(r'[-_\s]', '', text)]
    # 如果输入无短横，反推标准格式（pred485 → PRED-485）
    if '-' not in text and '_' not in text:
        m = re.match(r'^(.+?)(\d+)$', text.strip())
        if m:
            queries.append(f"{m.group(1).upper()}-{m.group(2)}")

    async def _search_one(q):
        if not q:
            return [], False
        try:
            return await run_sync(search_torrent, q, page, timeout=30)
        except Exception as e:
            jm_log('jm.mv.torrent', f'sukebei 搜索失败 (q={q})', e)
            return [], False

    for r, hn in await asyncio.gather(*[_search_one(q) for q in dict.fromkeys(queries)]):
        for item in r:
            b = _btih(item['magnet'])
            if b and b not in seen_btih:
                seen_btih.add(b)
                results.append(item)
        if hn:
            has_next = True

    # 合并 MissAV + JavDB + jav321 的磁链（BTIH 去重）
    extra = av_info.get('magnets', [])
    for m in extra:
        b = _btih(m['magnet'])
        if b and b not in seen_btih:
            seen_btih.add(b)
            results.append({'magnet': m['magnet'], 'seeders': -1})

    if not results:
        _clear_cooldown(cooldown_key)
        await mv_cmd.finish(f"❌ 未找到 {text.upper()} 的磁力链接")

    # 过滤死種：tracker seeders=0 排除，全死種时降级显示全部
    alive = [r for r in results if r.get('seeders', -1) == -1 or r.get('seeders', 0) > 0]
    display = alive if alive else results
    display.sort(key=lambda r: r.get('seeders', -1), reverse=True)
    display = display[:10]

    lines = []
    # 死種总数提示：dead = 所有结果中种子数为 0 的条目数
    dead_count = len(results) - len(alive)
    if dead_count > 0:
        lines.append(f"💡 已过滤 {dead_count} 个死種（共 {len(results)} 个结果）")

    for i, r in enumerate(display, 1):
        magnet = _clean_magnet(r['magnet'], text.upper())
        size = r.get('size', '')
        seeders = r.get('seeders', -1)
        leechers = r.get('leechers', 0)

        if seeders == -1:
            line = f"{i}. 🔗"
            if size:
                line += f"  {size}"
            lines.append(line)
            lines.append(f"   {magnet}")
        elif size:
            warning = ""
            if seeders == 0:
                warning = "  ⚠️死種"
            elif leechers >= seeders * 5 and seeders > 0:
                warning = "  ⚠️低存活"
            lines.append(f"{i}. {size}  👍{seeders} 👎{leechers}{warning}")
            lines.append(f"   {magnet}")
        else:
            lines.append(f"{i}. 👍{seeders} 👎{leechers}")
            lines.append(f"   {magnet}")

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
