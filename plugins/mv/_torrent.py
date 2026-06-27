import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

SUKEBEI_BASE = "https://sukebei.nyaa.si"


def search(query: str, page: int = 1):
    url = f"{SUKEBEI_BASE}/?q={quote(query, safe='')}&c=0_0&s=seeders&o=desc&p={page}"

    try:
        resp = httpx.get(url, headers=_headers(), timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return [], False

    results = _parse_page(resp.text)
    has_next = _has_next_page(resp.text)
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


def _parse_page(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_='table')
    if not table:
        return []

    results = []
    for row in table.select('tbody tr'):
        magnet_a = row.select_one('a[href^="magnet:"]')
        if not magnet_a:
            continue

        magnet = magnet_a['href']

        title_link = None
        for a in row.find_all('a', href=True):
            h = a['href']
            if '/view/' in h or (not h.startswith('magnet:') and not h.startswith('/download/') and not h.startswith('/?c=')):
                title_link = a
                break

        name = title_link.get_text(strip=True) if title_link else ''
        if not name:
            continue

        size = ''
        for td in row.find_all('td'):
            text = td.get_text(strip=True)
            if re.match(r'^\d+\.?\d*\s*(?:[KMGTP]i?B|B|bytes?)$', text):
                size = text
                break

        digit_cells = []
        for td in row.select('td.text-center'):
            txt = td.get_text(strip=True)
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


def _has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, 'html.parser')
    pag = soup.find('ul', class_='pagination')
    if pag:
        for a in pag.select('a[href]'):
            txt = a.get_text(strip=True)
            if txt == '›' or txt == '»' or 'next' in a.get('class', []):
                return True
    return False
