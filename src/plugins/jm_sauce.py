import asyncio
import base64
import os
import re
import time
from collections import deque
from typing import Any
from urllib.parse import quote

import httpx
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import is_type
from scrapling.parser import Selector

from jmcomic import jm_log

from jm_option import get_option as _get_option
from plugins.jm.common import _check_cooldown, _clear_cooldown

__plugin_name__ = "jm_sauce"
__plugin_usage__ = "/ss — 以图搜源（附图 / 回复含图消息 / 裸发自动用本群 2 分钟内最近一张图）"

ss_cmd = on_command("ss", priority=10, rule=is_type(GroupMessageEvent))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

ASCII2D_HOST = os.getenv("ASCII2D_HOST", "https://ascii2d.net")
SOUTU_BASE = "https://soutubot.moe"
TRACE_MOE_API = "https://api.trace.moe/search?anilistInfo"

_ss_semaphore = asyncio.Semaphore(2)
_tm_hits: deque[float] = deque()
_TM_MAX_PER_HOUR = 100

_soutu_m = 0
_SOUTU_FACTOR = "1.2"
_SOUTU_SOURCE_HOSTS = {
    "nhentai": "https://nhentai.net",
    "ehentai": "https://e-hentai.org",
    "exhentai": "https://exhentai.org",
    "panda": "https://panda.chaika.moe",
}


def _iter_image_data(message):
    """产出每个 image 段的 data dict（Message 对象与 OneBot array 格式通吃）。

    注意 nonebot 的 Message 是 list 子类，故按元素类型区分而非容器类型。
    """
    if message is None:
        return
    try:
        items = list(message)
    except TypeError:
        return
    for seg in items:
        if isinstance(seg, dict):
            data = seg.get("data")
            if seg.get("type") == "image" and isinstance(data, dict):
                yield data
        else:
            if getattr(seg, "type", None) == "image":
                data = getattr(seg, "data", None)
                if isinstance(data, dict):
                    yield data


def _extract_image_url(message) -> str | None:
    for d in _iter_image_data(message):
        url = str(d.get("url") or "").strip()
        if url.startswith("http"):
            return url
    return None


def _extract_image_file(message) -> str | None:
    for d in _iter_image_data(message):
        fid = str(d.get("file") or "").strip()
        if fid:
            return fid
    return None


_RECENT_IMAGES: dict[int, deque] = {}
_RECENT_TTL = 120
_RECENT_MAX = 5


def _record_group_image(event: GroupMessageEvent):
    """实时消息中的图片记入群级最近图缓存（供裸发 /ss 使用）。"""
    try:
        gid = int(event.group_id)
    except Exception:
        return
    for d in _iter_image_data(event.message):
        url = str(d.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        dq = _RECENT_IMAGES.setdefault(gid, deque())
        if not dq or dq[-1][1] != url:
            dq.append((time.time(), url))
            while len(dq) > _RECENT_MAX:
                dq.popleft()
        break


def _recent_group_image(group_id: int) -> str | None:
    dq = _RECENT_IMAGES.get(group_id)
    now = time.time()
    while dq and now - dq[0][0] > _RECENT_TTL:
        dq.popleft()
    return dq[-1][1] if dq else None


async def _get_image_fallback(bot: Bot, file_id: str):
    """OneBot get_image 兜底：优先换 http url，其次读 NapCat 本地缓存路径（与 NoneBot 同容器）。"""
    try:
        info = await bot.call_api("get_image", file=file_id)
    except Exception as e:
        jm_log('jm.sauce', f'get_image 失败(file={file_id[:40]}): {e}')
        return None
    info = info or {}
    url = str(info.get("url") or "").strip()
    if url.startswith("http"):
        return ("url", url)
    path = str(info.get("file") or "").strip()
    if path and os.path.isfile(path) and os.path.getsize(path) > 0:
        return ("path", path)
    jm_log('jm.sauce', f'get_image 返回不可用（url 空/路径无效）: {info}')
    return None


async def _resolve_image(bot: Bot, event: GroupMessageEvent):
    """返回 ("url", value) / ("path", value)；取不到图时返回 (None, 提示语)。"""
    # 1. 当前消息附图
    url = _extract_image_url(event.message)
    if url:
        return ("url", url)

    # 2. 回复引用的消息：get_msg → url → get_image → 本地路径。
    #    任一环节失败即终止并提示——不降级到最近图（用户意图明确指向被回复的那张图）。
    reply_seg = next((seg for seg in event.message if getattr(seg, "type", None) == "reply"), None)
    if reply_seg is not None:
        try:
            rid = int(str(reply_seg.data.get("id", "")).strip() or 0)
        except (ValueError, AttributeError, KeyError):
            rid = 0
        if rid <= 0:
            jm_log('jm.sauce', f'reply 段缺少有效 id: {dict(reply_seg.data)}')
            return (None, "回复目标无效，无法定位图片")
        try:
            src = await bot.get_msg(message_id=rid)
        except Exception as e:
            jm_log('jm.sauce', f'获取被回复消息失败(id={rid}): {e}')
            return (None, f"获取被回复消息(id={rid})失败，请改为随命令附图后重试")
        src_msg = src.get("message") if isinstance(src, dict) else getattr(src, "message", None)
        url = _extract_image_url(src_msg)
        if url:
            return ("url", url)
        fid = _extract_image_file(src_msg)
        jm_log('jm.sauce', f'被回复消息(id={rid})无 http 图片 url(file={fid})，走 get_image 兜底')
        if fid:
            got = await _get_image_fallback(bot, fid)
            if got:
                return got
        return (None, f"被回复的消息(id={rid})中未找到可用图片")

    # 3. 群内最近图片记忆（裸发 /ss）
    rurl = _recent_group_image(int(event.group_id))
    if rurl:
        return ("url", rurl)
    return (None, "未找到可用图片：请随命令附图、回复一条含图的消息，或在本群发图后 2 分钟内裸发 /ss")


async def _fetch_image(client: httpx.AsyncClient, url: str) -> bytes:
    resp = await client.get(url, headers={"User-Agent": _UA}, timeout=30)
    resp.raise_for_status()
    if not resp.content:
        raise ValueError("empty image body")
    return resp.content


async def _safe(source: str, coro) -> Any:
    try:
        return await coro
    except Exception as e:
        jm_log('jm.sauce', f'{source} 查询失败', e)
        return []


def _parse_ascii2d(html: str):
    doc = Selector(html)
    items = []
    for box in doc.css(".item-box"):
        title = author = href = ""
        links = box.css(".detail-box a")
        if links:
            title = (links[0].text or "").strip()
            href = (links[0].attrib.get("href") or "").strip()
            if len(links) > 1:
                author = (links[1].text or "").strip()
        else:
            ext = box.css(".external")
            if ext:
                title = (ext[0].text or "").strip()
        if not title:
            continue
        items.append({"title": title, "author": author, "url": href})
    return items


async def _search_ascii2d(client: httpx.AsyncClient, img_bytes: bytes):
    files = {"file": ("image.jpg", img_bytes, "image/jpeg")}
    resp = await client.post(f"{ASCII2D_HOST}/search/file", files=files, timeout=60)
    resp.raise_for_status()
    color_url = str(resp.url)
    if "/color/" not in color_url:
        raise RuntimeError("ascii2d 未返回结果页")
    bovw_url = color_url.replace("/color/", "/bovw/")
    bovw_resp = await client.get(bovw_url, timeout=30)
    results = [("特征", it) for it in _parse_ascii2d(bovw_resp.text)[:2]]
    results += [("色合", it) for it in _parse_ascii2d(resp.text)[:1]]
    return results


def _soutu_api_key(ua_len: int, m: int) -> str:
    ts = int(time.time())
    s = str(ts * ts + ua_len * ua_len + m)
    return "".join(reversed(base64.b64encode(s.encode()).decode().replace("=", "")))


async def _refresh_soutu(client: httpx.AsyncClient):
    global _soutu_m
    resp = await client.get(
        SOUTU_BASE + "/",
        headers={"User-Agent": _UA},
        timeout=30,
        follow_redirects=True,
    )
    match = re.search(r"m:\s*(-?\d+),", resp.text)
    m = int(match.group(1)) if match else 0
    if m <= 0:
        raise RuntimeError("soutubot 主页 m 解析失败")
    _soutu_m = m


async def _call_soutu(client: httpx.AsyncClient, img_bytes: bytes):
    files = {"file": ("image.jpg", img_bytes, "image/jpeg")}
    data = {"factor": _SOUTU_FACTOR}
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Origin": SOUTU_BASE,
        "Referer": SOUTU_BASE + "/",
        "X-Requested-With": "XMLHttpRequest",
        "X-Api-Key": _soutu_api_key(len(_UA), _soutu_m),
    }
    resp = await client.post(SOUTU_BASE + "/api/search", files=files, data=data, headers=headers, timeout=45)
    if resp.status_code in (401, 403):
        await _refresh_soutu(client)
        headers["X-Api-Key"] = _soutu_api_key(len(_UA), _soutu_m)
        resp = await client.post(SOUTU_BASE + "/api/search", files=files, data=data, headers=headers, timeout=45)
    resp.raise_for_status()
    return resp.json()


async def _search_soutubot(client: httpx.AsyncClient, img_bytes: bytes):
    global _soutu_m
    if not _soutu_m:
        await _refresh_soutu(client)
    payload = await _call_soutu(client, img_bytes)
    rows = payload.get("data") or []
    out = []
    for r in rows[:3]:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        host = _SOUTU_SOURCE_HOSTS.get(str(r.get("source") or ""), "")
        path = r.get("subjectPath") or ""
        out.append({
            "title": title,
            "lang": "汉化" if r.get("language") == "cn" else "",
            "url": host + path if host and path.startswith("/") else "",
            "sim": f"{r['similarity']}%" if str(r.get("similarity", "")).strip() else "",
        })
    return out


def _tm_allow() -> bool:
    now = time.time()
    while _tm_hits and now - _tm_hits[0] > 3600:
        _tm_hits.popleft()
    if len(_tm_hits) >= _TM_MAX_PER_HOUR:
        return False
    _tm_hits.append(now)
    return True


def _fmt_seconds(s: float) -> str:
    s = max(int(s), 0)
    return f"{s // 60:02d}:{s % 60:02d}"


async def _search_tracemoe(client: httpx.AsyncClient, img_bytes: bytes):
    if not _tm_allow():
        jm_log('jm.sauce', 'trace.moe 本小时额度已用完，跳过')
        return []
    resp = await client.post(
        TRACE_MOE_API,
        content=img_bytes,
        headers={"Content-Type": "image/jpeg", "User-Agent": _UA},
        timeout=45,
    )
    resp.raise_for_status()
    results = (resp.json().get("result")) or []
    out = []
    for r in results[:2]:
        a = r.get("anilist") or {}
        titles = [t for t in ((a.get("title") or {}).get(k) for k in ("native", "romaji", "english")) if t]
        out.append({
            "name": titles[0] if titles else "?",
            "episode": r.get("episode") or "?",
            "time": _fmt_seconds(float(r.get("from") or 0)),
            "sim": round(float(r.get("similarity") or 0) * 100, 1),
            "r18": bool(a.get("isAdult")),
        })
    return out


def _parse_yandex(html: str):
    doc = Selector(html)
    blocks = doc.css(".CbirSites-Item") or doc.css(".SitesServer-item")
    items = []
    for b in blocks[:4]:
        a = b.css("a[href^='http']")
        if not a:
            continue
        href = a[0].attrib.get("href") or ""
        t = b.css(".CbirSites-ItemTitle, .SitesServer-item-title")
        text = (t[0].text or "").strip() if t else ""
        if not text:
            text = (a[0].text or "").strip()
        if not text or not href.startswith("http"):
            continue
        items.append({"title": text[:60], "url": href})
        if len(items) >= 2:
            break
    return items


async def _search_yandex(client: httpx.AsyncClient, image_url: str):
    if not image_url:
        return []
    url = f"https://yandex.com/images/search?rpt=imageview&url={quote(image_url, safe='')}"
    resp = await client.get(url, headers={"User-Agent": _UA}, timeout=30)
    if "captcha" in resp.text.lower():
        jm_log('jm.sauce', 'yandex 触发验证码，本源降级跳过')
        return []
    return _parse_yandex(resp.text)


def _clean_title_for_jm(title: str) -> str:
    t = re.sub(r"[《》\[\]()（）【】「」『』]", " ", title)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:30]


async def _match_jm(title: str):
    q = _clean_title_for_jm(title)
    if len(q) < 4:
        return None
    option = _get_option()
    async with option.new_jm_async_client() as cl:
        page = await asyncio.wait_for(cl.search_site(q, 1), timeout=20)
    first = next(iter(page), None)
    if first:
        return {"id": first[0], "title": first[1]}
    return None


@ss_cmd.handle()
async def handle_ss(bot: Bot, event: GroupMessageEvent):
    cooldown_key = f"ss:{event.user_id}"
    remaining = _check_cooldown(cooldown_key)
    if remaining:
        await ss_cmd.finish(f"操作太频繁，请 {remaining} 秒后再试")

    kind, value = await _resolve_image(bot, event)
    if kind is None:
        _clear_cooldown(cooldown_key)
        await ss_cmd.finish(value)
        return

    await ss_cmd.send("🔍 正在反查图片来源（Ascii2d / SoutuBot / trace.moe / Yandex）……")

    async with _ss_semaphore:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if kind == "path":
                with open(value, "rb") as f:
                    img_bytes = f.read()
                probe_url = ""
            else:
                img_bytes = await _fetch_image(client, value)
                probe_url = value
            a2d, soutu, tm, yx = await asyncio.gather(
                _safe("ascii2d", _search_ascii2d(client, img_bytes)),
                _safe("soutubot", _search_soutubot(client, img_bytes)),
                _safe("tracemoe", _search_tracemoe(client, img_bytes)),
                _safe("yandex", _search_yandex(client, probe_url)),
            )

    jm_hit = None
    match_title = (a2d[0][1]["title"] if a2d else "") or (soutu[0]["title"] if soutu else "")
    if match_title:
        jm_hit = await _safe("jm-match", _match_jm(match_title))

    lines = ["🔍 搜图结果"]
    if a2d:
        lines += ["", "── Ascii2d ──"]
        for tag, it in a2d:
            row = f"[{tag}] {it['title']}"
            if it["author"]:
                row += f" / {it['author']}"
            lines.append(row)
            if it["url"]:
                lines.append(f"  ↳ {it['url']}")
    if soutu:
        lines += ["", "── SoutuBot ──"]
        for it in soutu:
            lang = f" ({it['lang']})" if it["lang"] else ""
            sim = f" {it['sim']}" if it["sim"] else ""
            lines.append(f"{it['title']}{lang}{sim}")
            if it["url"]:
                lines.append(f"  ↳ {it['url']}")
    if tm:
        lines += ["", "── 动画 (trace.moe) ──"]
        for it in tm:
            r18 = " [R18]" if it["r18"] else ""
            lines.append(f"{it['name']}{r18} 第{it['episode']}话 @{it['time']} ({it['sim']}%)")
    if yx:
        lines += ["", "── 网页 (Yandex) ──"]
        for it in yx:
            lines.append(it["title"])
            lines.append(f"  ↳ {it['url']}")

    if jm_hit and jm_hit.get("id"):
        lines += ["", f"✅ JM 疑似匹配: JM{jm_hit['id']}  {jm_hit['title'][:50]}",
                  f"发送 /jm {jm_hit['id']} 直接下载"]

    if len(lines) <= 1:
        await ss_cmd.finish("❌ 各数据源均未找到相似结果")

    await ss_cmd.finish("\n".join(lines))


_img_recorder = on_message(priority=5, block=False, rule=is_type(GroupMessageEvent))


@_img_recorder.handle()
async def handle_record_image(event: GroupMessageEvent):
    """被动记录群内图片消息，供裸发 /ss 时取「本群最近一张图」。"""
    _record_group_image(event)
