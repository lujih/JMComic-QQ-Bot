import concurrent.futures
import os
import re
from urllib.parse import urljoin

import httpx
from scrapling.parser import Selector
from jmcomic import jm_log

from plugins.mv._search_missav import search_missav
from plugins.mv._search_javdb import search_javdb

JAV321_BASE = os.getenv("JAV321_BASE_URL", "https://www.jav321.com")
_TIMEOUT = 20

FIELDS_FIRST = {'title', 'cover', 'date', 'studio', 'duration', 'favorites', 'director', 'series', 'rating'}
FIELDS_UNION = {'actresses', 'categories', 'magnets'}

def _search_with_timeout(fn, code, timeout):
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn, code)
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        jm_log('jm.mv.search', f'{fn.__name__} 超时 ({timeout}s)，跳过')
        return {}
    except Exception as e:
        jm_log('jm.mv.search', f'{fn.__name__} 异常', e)
        return {}
    finally:
        pool.shutdown(wait=False)


def search_video(query: str) -> dict:
    code = _normalize_code(query)
    result = {}
    seen_btih = set()

    # 并行搜索三站，各站独立超时，互不阻塞
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    try:
        f_missav = pool.submit(_search_with_timeout, search_missav, code, 45)
        f_javdb = pool.submit(_search_with_timeout, search_javdb, code, 45)
        f_jav321 = pool.submit(_search_with_timeout, _search_jav321, code, 20)
        try:
            for future in concurrent.futures.as_completed(
                [f_missav, f_javdb, f_jav321], timeout=55
            ):
                data = future.result()
                if data:
                    _merge_result(result, data, seen_btih)
        except concurrent.futures.TimeoutError:
            jm_log('jm.mv.search', '搜索最终超时 (55s)')
    finally:
        pool.shutdown(wait=False)
    return result


def _merge_result(target: dict, source: dict, seen_btih: set):
    for k in FIELDS_FIRST:
        if k in source and source[k] and k not in target:
            target[k] = source[k]

    for k in FIELDS_UNION:
        if k in source and source[k]:
            if k == 'magnets':
                for m in source[k]:
                    btih = _btih(m['magnet'])
                    if btih not in seen_btih:
                        seen_btih.add(btih)
                        target.setdefault(k, []).append(m)
            else:
                existing = set(target.get(k, []))
                for item in source[k]:
                    if item not in existing:
                        existing.add(item)
                        target.setdefault(k, []).append(item)


# ── jav321 ──────────────────────────────────────────────────────────


def _search_jav321(code: str) -> dict:
    url = f"{JAV321_BASE}/video/{code}"

    html = _jav321_fetch(url)
    if html is None:
        html = _jav321_search(code)

    if html is None:
        return {}

    try:
        doc = Selector(html)
        return _jav321_parse(doc)
    except Exception as e:
        jm_log('jm.mv.search', 'jav321 parse failed', e)
        return {}


def _jav321_fetch(url: str) -> str | None:
    try:
        with httpx.Client() as client:
            resp = client.get(url, headers=_jav321_headers(), timeout=_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        jm_log('jm.mv.search', 'jav321 request failed', e)
        return None
    except Exception as e:
        jm_log('jm.mv.search', 'jav321 request failed', e)
        return None


def _jav321_search(query: str) -> str | None:
    url = f"{JAV321_BASE}/search"
    try:
        with httpx.Client() as client:
            resp = client.post(url, data={'sn': query.strip()}, headers=_jav321_headers(), timeout=_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        jm_log('jm.mv.search', 'jav321 search failed', e)
        return None


def _jav321_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,zh-CN;q=0.9,en;q=0.8",
    }


def _jav321_parse(doc: Selector) -> dict:
    heading = doc.css('.panel-heading h3')
    if not heading:
        return {}

    title = heading[0].text.strip()
    if not title:
        return {}

    info = {'title': title}

    cover = _jav321_cover(doc)
    if cover:
        info['cover'] = cover

    info_panel = doc.css('.panel-body .col-md-9')
    if info_panel:
        panel = info_panel[0]

        for b in panel.css('b'):
            label = b.text.strip()

            if label in ('メーカー', 'Maker', 'Studio', '發行商'):
                next_a = b.xpath('./following-sibling::a[1]')
                if next_a:
                    info['studio'] = next_a[0].text.strip()
            elif label in ('収録時間', '播放時間', '播放時長', '時長', 'Play time'):
                txt = b.xpath('./following-sibling::text()[1]')
                text = (txt[0].text if txt else '').strip().lstrip(': \t')
                if text:
                    info['duration'] = text
            elif label in ('配信開始日', '發售日', '發行日期', '發行日', 'Release Date'):
                txt = b.xpath('./following-sibling::text()[1]')
                text = (txt[0].text if txt else '').strip().lstrip(': \t')
                if re.search(r'\d{4}', text):
                    info['date'] = text
            elif label in ('お気に入り登録数', '收藏', '評分', '讚', '贊', 'Likes', 'Favorites'):
                txt = b.xpath('./following-sibling::text()[1]')
                text = (txt[0].text if txt else '').strip().lstrip(': \t')
                m = re.search(r'\d+', text)
                if m:
                    info['favorites'] = m.group()

        actresses = []
        for a in panel.css('a[href^="/star/"]'):
            name = a.text.strip()
            if name and name not in actresses:
                actresses.append(name)
        if actresses:
            info['actresses'] = actresses

    magnets = []
    seen_btih = set()
    for a in doc.css('a[href^="magnet:"]'):
        href = a.attrib['href']
        key = _btih(href)
        if key not in seen_btih:
            seen_btih.add(key)
            magnets.append({'magnet': href})
    if magnets:
        info['magnets'] = magnets

    return info


def _jav321_cover(doc: Selector) -> str:
    sel = doc.css('div.col-md-3 div.col-md-12 img')
    if sel and sel[0].attrib.get('src'):
        url = _resolve_url(sel[0].attrib['src'].strip())
        if url:
            return url

    sel = doc.css('.panel-body .col-md-3 img')
    if sel and sel[0].attrib.get('src'):
        url = _resolve_url(sel[0].attrib['src'].strip())
        if url:
            return url

    return ''


# ── Shared utilities ────────────────────────────────────────────────


def _normalize_code(query: str) -> str:
    code = query.strip().lower()
    code = code.replace('-', '').replace('_', '').replace(' ', '')

    m = re.match(r'^(.+?)(\d+)$', code)
    if m:
        prefix, num = m.group(1), m.group(2)
        num = num.zfill(5)
        return prefix + num

    return code


def _resolve_url(src: str, base: str = JAV321_BASE) -> str:
    if not src:
        return ''
    if src.startswith('http://') or src.startswith('https://'):
        url = src
    elif src.startswith('//'):
        url = f'https:{src}'
    else:
        url = urljoin(base.rstrip('/') + '/', src.lstrip('/'))
    return re.sub(r'(?<!:)//', '/', url)


def _btih(magnet: str) -> str:
    m = re.search(r'btih:([a-fA-F0-9]+)', magnet)
    return m.group(1).lower() if m else magnet
