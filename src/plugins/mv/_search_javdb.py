import os
import re

from jmcomic import jm_log

JAVDB_BASE = os.getenv("JAVDB_BASE_URL", "https://javdb.com")
_TIMEOUT = 45


def _get_fetcher():
    try:
        from scrapling.fetchers import StealthyFetcher
        StealthyFetcher.adaptive = True
        return StealthyFetcher
    except ImportError:
        jm_log('jm.mv.javdb', "StealthyFetcher 不可用，无法请求 JavDB")
        return None


def search_javdb(code: str) -> dict:
    fetcher = _get_fetcher()
    if fetcher is None:
        return {}

    url = f"{JAVDB_BASE}/v/{code.upper()}"

    try:
        doc = fetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            timeout=_TIMEOUT,
            network_idle=True,
        )
    except Exception as e:
        jm_log('jm.mv.javdb', 'JavDB 请求失败', e)
        return {}

    info = {}

    try:
        # Title: og:title > h1 > title tag
    og = doc.css('meta[property="og:title"]')
    if og:
        info['title'] = og[0].attrib.get('content', '').strip()

    if not info.get('title'):
        h1 = doc.css('h1')
        if h1:
            t = h1[0].text.strip()
            # JavDB title often has code prefix like "MDBK-331 "
            info['title'] = t

    if not info.get('title'):
        title_tag = doc.css('title')
        if title_tag:
            t = title_tag[0].text.strip()
            t = re.sub(r'\s*[-–|]\s*JavDB.*$', '', t, flags=re.IGNORECASE).strip()
            if t:
                info['title'] = t

    if not info.get('title'):
        return {}

    # Cover: og:image > video cover > any large image
    og_img = doc.css('meta[property="og:image"]')
    if og_img:
        info['cover'] = og_img[0].attrib.get('content', '').strip()

    if not info.get('cover'):
        for sel in (
            '.column-video-cover img',
            '.video-cover img',
            '.cover img',
            'img.video-cover',
            'img[alt*="cover" i]',
        ):
            img = doc.css(sel)
            if img and img[0].attrib.get('src'):
                info['cover'] = img[0].attrib['src'].strip()
                break

    # Metadata panel (JavDB uses dt/dd pairs)
    for panel_sel in ('.videos dd', 'dl dd', '.meta dd', '.info dd'):
        dds = doc.css(panel_sel)
        if not dds:
            continue
        break
    else:
        dds = None

    if dds:
        for dd in dds:
            text = dd.text.strip()

            # dt sibling tells us the field name
            dt = dd.xpath('./preceding-sibling::dt[1]')
            if not dt:
                continue
            label = dt[0].text.strip().lower()

            if any(k in label for k in ('date', 'release', '配信', '発売', '發售')):
                if re.search(r'\d{4}', text) and 'date' not in info:
                    info['date'] = text
            elif any(k in label for k in ('duration', 'time', '収録', '播放', '時長')):
                if 'duration' not in info:
                    info['duration'] = text
            elif any(k in label for k in ('maker', 'studio', 'メーカー', '製作', '廠商')):
                a = dd.css('a')
                info['studio'] = a[0].text.strip() if a else text
            elif any(k in label for k in ('director', '監督', '导演')):
                info['director'] = text
            elif any(k in label for k in ('series', 'シリーズ', '系列')):
                a = dd.css('a')
                info['series'] = a[0].text.strip() if a else text
            elif any(k in label for k in ('rating', 'score', '評分', '评分')):
                m = re.search(r'[\d.]+', text)
                if m:
                    info['rating'] = m.group()

    # Categories
    seen_cat = set()
    categories = []
    for sel in ('a[href*="/tags/"]', 'a[href*="/genre/"]', 'a[href*="/category/"]',
                '.categories a', '.tags a', '[class*="tag"] a'):
        for a in doc.css(sel):
            name = a.text.strip()
            if name and name not in seen_cat:
                seen_cat.add(name)
                categories.append(name)
    if categories:
        info['categories'] = categories

    # Actresses
    seen_act = set()
    actresses = []
    for sel in ('a[href*="/actors/"]', 'a[href*="/star/"]', 'a[href*="/actress/"]',
                '.actors a', '.stars a', '[class*="actor"] a', '[class*="star"] a'):
        for a in doc.css(sel):
            name = a.text.strip()
            if name and name not in seen_act:
                seen_act.add(name)
                actresses.append(name)
    if actresses:
        info['actresses'] = actresses
    except Exception as e:
        jm_log('jm.mv.javdb', 'JavDB 解析失败', e)

    return info
