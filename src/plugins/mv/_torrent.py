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
        with httpx.Client() as client:
            resp = client.get(url, headers=_headers(), timeout=30, follow_redirects=True)
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

    col_indices = _get_column_indices(table[0])
    seeders_idx = leechers_idx = None
    if col_indices:
        seeders_idx, leechers_idx = col_indices

    results = []
    for row in table[0].css('tbody tr'):
        magnet_a = row.css('a[href^="magnet:"]')
        if not magnet_a:
            continue

        magnet = magnet_a[0].attrib['href']

        title_link = None
        for a in row.css('a[href]'):
            h = a.attrib.get('href', '')
            if '/view/' in h or (not h.startswith('magnet:') and not h.startswith('/download/') and not h.startswith('/?c=') and not h.startswith('/user/')):
                title_link = a
                break

        name = (title_link.text or '').strip() if title_link else ''
        if not name:
            continue

        size = ''
        for td in row.css('td'):
            text = (td.text or '').strip()
            if re.match(r'^\d+(?:\.\d+)?\s*(?:[KMGTP]i?B|B|bytes?)$', text):
                size = text
                break

        # Sukebei 列序: category | name | download | size | seeders | leechers | completed
        cols = row.css('td')
        if seeders_idx is not None and leechers_idx is not None:
            try:
                seeders = int((cols[seeders_idx].text or '0').strip())
            except (ValueError, IndexError):
                seeders = 0
            try:
                leechers = int((cols[leechers_idx].text or '0').strip())
            except (ValueError, IndexError):
                leechers = 0
        elif len(cols) >= 3:
            try:
                seeders = int((cols[-3].text or '0').strip())
            except (ValueError, IndexError):
                seeders = 0
            try:
                leechers = int((cols[-2].text or '0').strip())
            except (ValueError, IndexError):
                leechers = 0
        else:
            seeders = 0
            leechers = 0

        results.append({
            'name': name,
            'magnet': magnet,
            'size': size,
            'seeders': seeders,
            'leechers': leechers,
        })

    return results


def _get_column_indices(table):
    thead = table.css('thead tr th')
    if not thead:
        return None
    seeders_idx = leechers_idx = None
    for i, th in enumerate(thead):
        text = (th.text or '').strip().lower()
        if 'seeders' in text:
            seeders_idx = i
        elif 'leechers' in text:
            leechers_idx = i
    if seeders_idx is not None and leechers_idx is not None:
        return seeders_idx, leechers_idx
    return None


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
