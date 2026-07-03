import os
import re
from urllib.parse import quote

import httpx
from scrapling.parser import Selector
from jmcomic import jm_log

SUKEBEI_BASE = os.getenv("SUKEBEI_BASE_URL", "https://sukebei.nyaa.si")


def search(query: str, page: int = 1):
    url = f"{SUKEBEI_BASE}/?q={quote(query, safe='')}&c=0_0&s=seeders&o=desc&p={page}"

    try:
        resp = httpx.get(url, headers=_headers(), timeout=30, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        jm_log('jm.mv.torrent', 'sukebei 请求失败', e)
        return [], False

    doc = Selector(html)
    results = _parse_page(doc)
    has_next = _has_next_page(doc)
    return results, has_next


def _headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _parse_page(doc: Selector):
    table = doc.css('table.table')
    if not table:
        return []

    results = []
    for row in table[0].css('tbody tr'):
        magnet_a = row.css('a[href^="magnet:"]')
        if not magnet_a:
            continue

        magnet = magnet_a[0].attrib['href']

        title_link = None
        for a in row.css('a[href]'):
            h = a.attrib.get('href', '')
            if '/view/' in h or (not h.startswith('magnet:') and not h.startswith('/download/') and not h.startswith('/?c=')):
                title_link = a
                break

        name = title_link.text.strip() if title_link else ''
        if not name:
            continue

        size = ''
        for td in row.css('td'):
            text = td.text.strip()
            if re.match(r'^\d+\.?\d*\s*(?:[KMGTP]i?B|B|bytes?)$', text):
                size = text
                break

        cells = row.css('td')[-3:]
        digit_cells = []
        for td in cells:
            txt = td.text.strip()
            if txt.isdigit():
                digit_cells.append(int(txt))

        seeders = digit_cells[-2] if len(digit_cells) >= 2 else 0
        leechers = digit_cells[-1] if len(digit_cells) >= 1 else 0

        results.append({
            'name': name,
            'magnet': magnet,
            'size': size,
            'seeders': seeders,
            'leechers': leechers,
        })

    return results


def _has_next_page(doc: Selector) -> bool:
    pag = doc.css('ul.pagination')
    if pag:
        lis = pag[0].css('li')
        if len(lis) >= 2:
            last_li = lis[-1]
            classes = last_li.attrib.get('class', '')
            if 'disabled' not in classes.split():
                return True
    return False
