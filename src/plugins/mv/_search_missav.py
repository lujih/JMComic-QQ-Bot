import os
import re

from jmcomic import jm_log

MISSAV_BASE = os.getenv("MISSAV_BASE_URL", "https://missav.com")
_TIMEOUT = 45000


def _init_fetcher():
    try:
        from scrapling.fetchers import StealthyFetcher
        return StealthyFetcher
    except ImportError:
        jm_log('jm.mv.missav', "StealthyFetcher 不可用，无法请求 MissAV")
        return None


_FETCHER = _init_fetcher()


def _get_fetcher():
    return _FETCHER


def search_missav(code: str) -> dict:
    fetcher = _get_fetcher()
    if fetcher is None:
        return {}

    # 从归一化 code（如 "mdbk00331"/"200gana00123"）还原带连字符的 URL（"MDBK-331"/"200GANA-123"）
    m = re.match(r'^(.+?)(\d+)$', code)
    url_code = code.upper()
    if m:
        prefix = m.group(1).upper()
        num = m.group(2).lstrip('0') or '0'
        url_code = f"{prefix}-{num}"
    url = f"{MISSAV_BASE}/{url_code}"

    try:
        doc = fetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            retries=1,
            timeout=_TIMEOUT,
            network_idle=False,
        )
    except Exception as e:
        jm_log('jm.mv.missav', 'MissAV 请求失败', e)
        return {}

    info = {}

    try:
        # Title: og:title > h1
        og = doc.css('meta[property="og:title"]')
        if og:
            info['title'] = og[0].attrib.get('content', '').strip()

        if not info.get('title'):
            h1 = doc.css('h1')
            if h1:
                info['title'] = (h1[0].text or '').strip()

        if not info.get('title'):
            return {}

        # Cover: og:image > various img selectors
        og_img = doc.css('meta[property="og:image"]')
        if og_img:
            info['cover'] = og_img[0].attrib.get('content', '').strip()

        if not info.get('cover'):
            for sel in (
                'img.aspect-video',
                'div.aspect-video img',
                'img[alt*="cover" i]',
                'img[alt*="video" i]',
                'div.relative img',
            ):
                img = doc.css(sel)
                if img and img[0].attrib.get('src'):
                    info['cover'] = img[0].attrib['src'].strip()
                    break

        # Metadata: scan label-value pairs in various container patterns
        for dt_sel in ('dt', 'span.text-gray-500', '[class*="label"]', 'th'):
            containers = doc.css(f'{dt_sel}')
            if not containers:
                continue
            for label_el in containers:
                label = (label_el.text or '').strip().lower()

                dd = label_el.xpath('./following-sibling::dd[1]')
                if not dd:
                    dd = label_el.xpath('./following-sibling::*[1]')
                if not dd:
                    continue

                value_el = dd[0]
                text = (value_el.text or '').strip()

                if any(k in label for k in ('date', 'release', '配信', '発売', '發售')):
                    if re.search(r'\d{4}', text) and 'date' not in info:
                        info['date'] = text
                elif any(k in label for k in ('duration', 'time', '収録', '播放', '時長')):
                    if 'duration' not in info:
                        info['duration'] = text
                elif any(k in label for k in ('maker', 'studio', 'メーカー', '製作')):
                    a = value_el.css('a')
                    info['studio'] = (a[0].text or '').strip() if a else text
                elif any(k in label for k in ('director', '監督', '导演')):
                    info['director'] = text
                elif any(k in label for k in ('series', 'シリーズ')):
                    info['series'] = text

        # Categories/tags
        seen_cat = set()
        categories = []
        for sel in ('a[href*="/tag/"]', 'a[href*="/genre/"]', 'a[href*="/category/"]',
                    '[class*="tag"] a', '[class*="genre"] a', '[class*="category"] a'):
            for a in doc.css(sel):
                name = (a.text or '').strip()
                if name and name not in seen_cat:
                    seen_cat.add(name)
                    categories.append(name)
        if categories:
            info['categories'] = categories

        # Actresses
        seen_act = set()
        actresses = []
        for sel in ('a[href*="/actress/"]', 'a[href*="/star/"]', 'a[href*="/actor/"]',
                    '[class*="actress"] a', '[class*="star"] a'):
            for a in doc.css(sel):
                name = (a.text or '').strip()
                if name and name not in seen_act:
                    seen_act.add(name)
                    actresses.append(name)
        if actresses:
            info['actresses'] = actresses

        # Magnets
        magnets = []
        seen_btih = set()
        for a in doc.css('a[href^="magnet:"]'):
            href = a.attrib['href']
            m = re.search(r'btih:([a-fA-F0-9]+)', href)
            key = m.group(1).lower() if m else href
            if key not in seen_btih:
                seen_btih.add(key)
                magnets.append({'magnet': href, 'seeders': -1})
        if magnets:
            info['magnets'] = magnets
    except Exception as e:
        jm_log('jm.mv.missav', 'MissAV 解析失败', e)

    return info
